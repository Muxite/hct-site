# Architecture

How the HCT Site pieces fit together. For the product brief and milestone plan
see [`../PLANS.md`](../PLANS.md); this document is the technical reference.

## Overview

Two halves that meet at one **database** (Supabase):

- **Generate** (Python, backend, on-demand): read the CV (primary; optional
  Scholar scrape, off by default) → change-detect → deterministic per-entry
  parse with per-entry LLM fallback → validate → upsert to Supabase
  (`publications` + the full `timeline`); `sync-content` fills `people`/`research`
  (from editable YAML with current/archive status) and `site_content`
  (header/nav + prose) from `site.yaml`.
- **Render** (React + Vite app, browser): query Supabase with the publishable
  key → render the year-grouped timeline, people, research, and prose sections.

The **database tables are the contract** (see `FRONTEND-DB.md`). The backend
writes with the secret key; the frontend reads with the publishable key under
row-level security. Neither side knows about the other beyond the table shapes.

```
GENERATE (backend, one-shot)                         RENDER (browser)
┌─────────────┐   HTTP    ┌──────────┐
│ hct-manager │ ───────►  │   ujin   │ ──► HTTP / obscura / sitemap / RSS
│             │ ◄───────  │  scrape  │      (fallback chain)
└─────┬───────┘ fingerprint└──────────┘
      │ + page text
      │
      │ changed?  ── no ──► stop (no-op run)
      │ yes
      ▼
  LLM (OpenRouter, Gemini 3 Flash)  ◄── few-shot examples; style profile (describe)
      │
      ▼
  Pydantic validation (+1 repair retry)
      │
      ▼  upsert (secret key)
  ┌──────────────────────────────┐   query (publishable key)   ┌─────────────┐
  │ Supabase: publications,      │ ◄────────────────────────── │  React +    │
  │ timeline, people, research,  │                             │  Vite app   │
  │ site_content   (RLS: read)   │ ──────────────────────────► │ (frontend/) │
  └──────────────────────────────┘                             └─────────────┘
```

## Components

### ujin (scrape service) — `backend/ujin`, git submodule

Black-box dependency. Exposes a FastAPI scrape service on `:8901`
(`POST /scrape`). Handles the HTTP → obscura (headless browser) → sitemap → RSS
fallback chain and returns a normalized payload including a stable
**`fingerprint`** (SHA-256 of the normalized content). We never modify ujin.

Two build targets: `ujin` (pure-python, fast) and `ujin-full` (bundles the
obscura renderer; needed for anti-bot/JS-heavy pages like Google Scholar).

### hct-manager — `backend`

The program we own. Modules:

| Module              | Responsibility                                                        |
| ------------------- | --------------------------------------------------------------------- |
| `config.py`         | Env-driven config (LLM key/model, ujin URL, Supabase URL + keys, paths). |
| `models.py`         | Pydantic schema: `Publication`/`PublicationSet`, `TimelineEntry`, `Person`, `ResearchProject`, `SiteContent`; `slug_for`. |
| `supabase_client.py`| Thin PostgREST client (upsert/replace/select) — writes via the secret key. |
| `ujin_client.py`    | HTTP client for `/scrape`; normalizes the response.                   |
| `state.py`          | Per-source fingerprint + cached papers (change detection).            |
| `llm.py`            | OpenRouter chat client (Gemini 3 Flash); records token/latency metrics. |
| `extract.py`        | Prompt → LLM → JSON → validate, with one repair retry.                |
| `style.py`          | Read a document (incl. `.docx`) → short LLM style profile.            |
| `describe.py`       | Opt-in: write a short lab-voice `description` per paper.              |
| `timeline.py`       | Build the timeline — full publication history, newest first (year-based, blurb reused from `description`). |
| `cv_parse.py`       | Deterministic CV entry parser (split → heuristics → Pydantic) + ParseOutcome records. |
| `sync_content.py`   | people.yaml / research.yaml (status: current/alumni/archived) → people/research tables. |
| `content.py`        | `load_site_yaml`: site.yaml (header/nav + prose) → site_content rows (+ legacy HTML + QA text helpers). |
| `orchestrate.py`    | Tie it together; merge sources (CV wins dedupe); upsert publications + timeline. |
| `cli.py`            | `run` / `sync-content` / `analyze-style` / `describe` / `qa` / `health`. |

### frontend — `frontend/` (React + Vite)

A Vite single-page app. `src/data/db.js` builds the supabase-js client from Vite
env (`VITE_SB_URL` / `VITE_SB_PUBLISHABLE_KEY`) and exposes the same getters as
before. `App.jsx` loads everything once and renders: `Timeline` (the centerpiece —
full history grouped by year, the publications list folded in), `People`
(current + alumni), `Research` (current + past projects), and prose `Section`s
from `site_content`; `PaperDetail` is a `?paper=<slug>` view. Pure presentation
logic lives in `src/lib/format.js` (year grouping, kind splitting, labels) and is
unit-tested. See `docs/FRONTEND-DB.md` for the table contract and
`frontend/README.md` for dev/build.

## Data flow details

### Change detection & the source union

Fels and Ashjaee co-author papers, so the published set is the **deduped union**
of all sources. To avoid re-running the LLM on unchanged sources while still
producing a complete set, each source's extracted papers are cached in its state
file (`data/state/<key>.json`) alongside its fingerprint:

- changed source → re-scrape, re-extract, refresh cache;
- unchanged source → reuse cached papers;
- merge all sources, dedupe by `id`, upsert to Supabase — **only if** at least
  one source changed (or `--force`). An idle run writes nothing.

`id` is a deterministic slug (`<firstauthorlast><year>-<title>`) computed by
hct-manager, not trusted from the LLM, so the same paper always dedupes.

### Validation & repair

The LLM is asked for JSON matching `PublicationSet` (minus `id`). We parse,
compute ids, and validate. On any parse/validation failure we send one repair
message containing the error and retry; a second failure aborts the run with a
clear error rather than writing bad data.

## Configuration & secrets

`.env` (gitignored) holds `OPENROUTER_API_KEY` and the Supabase values
(`SB_URL`, `SB_SEC_KEY` for backend writes, `SB_PUB_KEY` for the frontend, with
`SB_SERVICE_ROLE_KEY`/`SB_ANON_PUB_KEY` as legacy fallbacks); docker compose
injects them. The **secret** key bypasses RLS (writes); the **publishable** key
is read-only and safe to embed in the frontend (`frontend/.env`, `VITE_SB_*`). All paths and
the model are overridable via env (see `backend/README.md`). Editable
behavior lives under `backend/data/` (mounted in): `sources/` (who to track),
`templates/` (prompts), `examples/` (few-shot), `state/` (fingerprints + style
profile), `inputs/` (style source docs).

## Testing

- Python: `pytest` in `backend` — every module has unit tests; the
  LLM and ujin are always faked (httpx `MockTransport` / fake objects). No live
  network or API calls in the suite.
- JS: `npm test` in `frontend` — Node's built-in test runner (`node --test`)
  against the pure presentation helpers in `src/lib/format.js`.

## Design decisions

- **Supabase is the source of truth.** The backend upserts every section with
  the secret key; the frontend reads with the publishable key under RLS, so a
  frontend dev only needs the URL + publishable key (`FRONTEND-DB.md`). RLS
  exposes read-only access; writes require the secret key and never touch the
  browser.
- **Full-history, year-based timeline.** The `timeline` mirrors the whole
  publication history (one row per paper, newest first) and the frontend groups
  it by year — that single table is the site's centerpiece. The CV/Scholar give
  only a publication year, so it stores `year` + a `date_label`, never a
  fabricated date. Blurbs are reused from `publications.description` (the opt-in
  `describe` step fills those), so a normal `run` makes no LLM calls for it.
- **Boilerplate is YAML, not HTML.** Header/nav and the prose sections come from
  an editable `site.yaml` in the mounted volume (→ `site_content`), so the copy
  is adjustable without touching the React app.
- **One-shot, not a daemon.** Polling is manual; the backend can be off most of
  the time and woken to check for updates. (Scheduling is future work.)
- **ujin is a black box.** No Scholar-specific parsing inside ujin; it fetches
  and renders, the LLM interprets. Keeps ujin reusable and hct-manager simple.
- **Don't trust the LLM blindly.** Deterministic ids + schema validation +
  repair retry keep generated data safe to publish.
