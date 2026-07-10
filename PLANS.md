# HCT Site — Plans & Architecture

> This file tracks roadmap/status. For the current technical reference, see
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (how the pieces fit together)
> and [`docs/FRONTEND-DB.md`](docs/FRONTEND-DB.md) (the Supabase table
> contract for frontend devs). `README.md` has the plain-language walkthrough.

A small, mostly-off automation pipeline for the HCT Lab website's content. The
lab's **CV (.docx)** is the primary publication source — dropped into
`dropbox/` or committed under `backend/data/inputs/` — parsed **deterministically
first** (`src/cv_parse.py`), with a per-entry LLM fallback only for entries the
heuristics can't fill (`src/cv.py`/`src/extract.py`). Google Scholar (via the
**ujin** submodule) is an optional, off-by-default secondary source. Everything
is written to **Supabase** (Postgres) — the single source of truth for the
frontend. The frontend is a **React + Vite** app that reads Supabase directly
with a publishable, read-only key; there is no server between the browser and
the database.

The design goal is still that the backend can be **off most of the time**: run
it (manually, or on a schedule later), let it check for changes via content
fingerprinting, upsert to Supabase if anything changed, then exit. Nothing
needs to stay running.

---

## 1. Current architecture (reality, not aspiration)

| Concern         | Now                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| Data store       | **Supabase / Postgres** (`db/schema.sql`) — `publications`, `timeline`, `people`, `research`, `project_people`, `site_content`, experimental `paper_samples` |
| Frontend reads   | React + Vite app queries Supabase directly with `supabase-js` (publishable key, RLS read-only) |
| Backend writes   | `hct-manager` upserts with a Supabase **secret** key; browser never sees it |
| Polling          | **Manual, one-shot** (`docker compose run --rm hct-manager run`); no scheduler yet |
| Backend uptime   | Run-to-completion, then exit                                        |

Supabase has been the store for a while now — see `CLAUDE.md`, `README.md`,
`docs/ARCHITECTURE.md`, `docs/FRONTEND-DB.md`, and `db/schema.sql` for the
full, current picture. There is no `frontend/data/*.yaml` static-render path
and no `hct-render/` directory in the current tree; those describe an earlier
design this file used to document.

---

## 2. Components (current)

- **`ujin`** (`backend/ujin/`, git submodule) — scrape microservice, FastAPI on
  `:8901`. Black box; used only for the optional, off-by-default Google
  Scholar path. See `docs/ARCHITECTURE.md` for the fallback chain.
- **`hct-manager`** (`backend/src/`, Python, CLI entry point `hct-manager`) —
  reads the CV (+ optional Scholar), change-detects via SHA-256 fingerprint,
  parses deterministically with per-entry LLM fallback (OpenRouter, Gemini 3
  Flash), validates with Pydantic, and upserts `publications` + the full
  `timeline` to Supabase. `sync-content` separately pushes `people.yaml` /
  `research.yaml` / `site.yaml` (and now `projects.yaml`, see §4) to Supabase.
  One-shot: `hct-manager run [--force]` does its work once and exits.
- **`frontend/`** (React + Vite) — reads Supabase tables directly with
  `VITE_SB_PUBLISHABLE_KEY` under RLS; no backend call from the browser. Also
  has an offline `VITE_MOCK` snapshot mode (`frontend/src/data/mockClient.js` +
  `snapshot.json`) for developing without live Supabase credentials.

Configuration lives in `.env`/`.env.example` at the repo root (backend:
`OPENROUTER_API_KEY`, `SB_URL`, `SB_SEC_KEY`, `SB_PUB_KEY`) and a separate
`frontend/.env` (`VITE_SB_URL`, `VITE_SB_PUBLISHABLE_KEY`).

---

## 3. Milestones (build order, historical)

These landed already; kept here as a record of build order rather than a
forward-looking plan:

1. Pydantic schema + validated I/O.
2. Frontend renderer (now: React components reading Supabase, not a YAML
   fetch — see §1).
3. `ujin` client + fingerprint-based change detection.
4. LLM extraction (CV-first, with prompt + repair retry).
5. Style analysis (lab-voice profile from a sample document).
6. Orchestration + CLI (`hct-manager run`, `sync-content`, `describe`, `qa`,
   `health`).
7. Containerization (`Dockerfile`, `docker-compose.yml`).
8. Docs (`README.md`, this file, `docs/`).
9. Migration from YAML-on-disk to Supabase as the data store (this is the
   change that made the "Current scope vs. future" table below obsolete).

---

## 4. In progress: project-centric restructure

A restructure that groups papers under featured **projects** (hero image,
project summary, member papers, per-paper audience-targeted summaries) is
currently **mid-flight and uncommitted** in the working tree. Full design is
in [`docs/PROJECTS.md`](docs/PROJECTS.md); a short pointer also lives in
`docs/ARCHITECTURE.md`. Do not assume it is live in production until it lands
as a commit.

---

## 5. Open roadmap items

- [ ] Land the project-centric restructure (§4) as a commit/series of commits.
- [ ] AI clustering (`src/cluster.py`) and figure extraction are explicitly
  deferred within that restructure until the OpenRouter key is "re-enabled"
  (see the module's own docstring) — resolve what that gating refers to
  before shipping clustering.
- [ ] Scheduled/automated runs — currently fully manual
  (`docker compose run --rm hct-manager run`).
- [ ] Decide the long-term fate of the Google Scholar path — it's disabled by
  default (`HCT_SCHOLAR_ENABLED=1` to opt in) because scraping trips
  CAPTCHAs; if it won't be revived, consider formally deprecating it instead
  of carrying the `ujin`/Scholar code path indefinitely.
- [ ] Retire `publications.description` once `summary_plain` is populated
  everywhere (tracked in `docs/PROJECTS.md` "Open / defaulted").

## 6. Explicit non-goals (still true)

- No auth, no write API from the browser — the frontend only ever reads
  Supabase with a read-only publishable key; all writes go through the
  backend's secret key.
- No edits to `ujin` internals — it's a black-box submodule dependency.
