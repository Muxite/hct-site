# Architecture

How the HCT Site pieces fit together. For the product brief and milestone plan
see [`../PLANS.md`](../PLANS.md); this document is the technical reference.

## Overview

Two halves that meet at one **database** (Supabase):

- **Generate** (Python, backend, on-demand): scrape → change-detect → LLM
  extract → validate → upsert to Supabase (`publications` + `timeline`);
  `migrate-content` also fills `people`/`research`/`site_content`.
- **Render** (JavaScript, browser, on page load): query Supabase with the
  publishable key → hydrate each section.

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
  │ Supabase: publications,      │ ◄────────────────────────── │  index.html │
  │ timeline, people, research,  │                             │ + hct-render│
  │ site_content   (RLS: read)   │ ──────────────────────────► │  renderers  │
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
| `timeline.py`       | Build the 5-most-recent "Latest" timeline (year-based, AI blurb).     |
| `content.py`        | Parse static HTML → people/research/site_content rows (+ AI enrich).  |
| `orchestrate.py`    | Tie it together; merge sources; upsert publications + timeline to Supabase. |
| `cli.py`            | `run` / `import-html` / `migrate-content` / `analyze-style` / `describe` / `health`. |

### hct-render — `frontend/hct-render`

Browser ES modules. On load each renderer reads its data from Supabase via the
publishable key (`data/db.js`) and hydrates its section: `timeline.js`
(`#timeline-list`), `publications.js` (`#publications-list`, grouped by year),
`people.js` (`#people`), `research.js` (`#research`). The static markup in each
section is the no-JS / DB-unreachable fallback. See `docs/FRONTEND-DB.md` for the
table contract.

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
is read-only and safe to embed in `frontend/hct-render/config.js`. All paths and
the model are overridable via env (see `backend/README.md`). Editable
behavior lives under `backend/data/` (mounted in): `sources/` (who to track),
`templates/` (prompts), `examples/` (few-shot), `state/` (fingerprints + style
profile), `inputs/` (style source docs).

## Testing

- Python: `pytest` in `backend` — every module has unit tests; the
  LLM and ujin are always faked (httpx `MockTransport` / fake objects). No live
  network or API calls in the suite.
- JS: `npm test` in `frontend/hct-render` — Node's built-in test runner against
  the pure render functions and renderers/db getters with injected deps.

## Design decisions

- **Supabase is the source of truth.** The backend upserts every section with
  the secret key; the static frontend reads with the publishable key under RLS,
  so a frontend dev only needs the URL + publishable key (`FRONTEND-DB.md`). RLS
  exposes read-only access; writes require the secret key and never touch the
  browser.
- **Year-based timeline.** Scholar profiles give only a publication year, so the
  `timeline` stores `year` + a `date_label` rather than a fabricated date.
- **One-shot, not a daemon.** Polling is manual; the backend can be off most of
  the time and woken to check for updates. (Scheduling is future work.)
- **ujin is a black box.** No Scholar-specific parsing inside ujin; it fetches
  and renders, the LLM interprets. Keeps ujin reusable and hct-manager simple.
- **Don't trust the LLM blindly.** Deterministic ids + schema validation +
  repair retry keep generated data safe to publish.
