# CLAUDE.md — HCT Site

Auto-updates the HCT Lab website. The lab's **CV (.docx)** is the primary
publication source: dropped into `dropbox/` (mounted to `/app/data/inbox`) or
committed under `backend/data/inputs/`, parsed **deterministically first**
(`src/cv_parse.py`), with a per-entry LLM fallback only for entries the
heuristics can't fill (`src/cv.py`). Google Scholar (via the **ujin**
submodule) is an optional secondary source, **disabled by default**
(`HCT_SCHOLAR_ENABLED=1` to opt in — scraping it trips CAPTCHAs); on duplicate
papers the **CV wins**. The timeline is the **full publication history** (newest
first, grouped by year in the frontend) — the site's centerpiece. People and
research projects come from editable `people.yaml` / `research.yaml` with explicit
current/alumni/archived status, and the site boilerplate (header/nav + prose
sections) from `site.yaml` (`src/sync_content.py`, `src/content.py`). Everything
is written to **Supabase** (the single source of truth for the frontend). The
frontend is a **React + Vite** app that reads Supabase directly with a publishable
key (`frontend/`).

## Layout

```
docker-compose.yml     ujin + one-shot hct-manager (run from repo root)
.env / .env.example    OPENROUTER_API_KEY + SB_* (gitignored)
dropbox/               drop folder (gitignored): CV docx + people/research/site YAML
db/schema.sql          Supabase tables + RLS (people.kind, research.kind)
docs/                  ARCHITECTURE.md, FRONTEND-DB.md
frontend/              React + Vite app (src/, reads Supabase; own .env: VITE_SB_*)
backend/
  pyproject.toml       package metadata (package name: src)
  Dockerfile
  src/                 the Python agent (cli, config, llm, cv, cv_parse,
                       extract, describe, timeline, sync_content, content,
                       orchestrate, qa, metrics, ...)
  tests/               unit tests — LLM + network ALWAYS mocked
  data/                sources/ templates/ inputs/ state/ inbox/  (mounted)
  ujin/                scraper service (git submodule; black box, do not edit)
experiments/           agent performance harness + plots (token/error/hallucination)
```

## Commands

```bash
# Python tests (from backend/)
cd backend && PYTHONPATH=. pytest

# CLI (installed entry point `hct-manager`, or `python3 -m src.cli`)
hct-manager run [--force]        # CV parse (+ optional Scholar) -> upsert pubs + full timeline
hct-manager sync-content         # people.yaml/research.yaml/site.yaml -> Supabase
hct-manager describe --fetch     # per-paper lab-voice description (shortened from source)
hct-manager qa                   # QA report on the live Supabase data
hct-manager health               # check the ujin scrape service
hct-manager viewer               # localhost read+edit data viewer (needs [viewer] extra)

# Frontend (React + Vite) — from frontend/
cd frontend && npm install && npm run dev   # dev server (needs frontend/.env)
npm test                                     # pure-helper unit tests (node --test)
npm run build                                # production build -> frontend/dist/

# Deterministic CV parse smoke (no LLM, no network)
cd backend && PYTHONPATH=. python3 -c "
from src.cv import publications_section, read_cv_text
from src.cv_parse import parse_cv_entries
pubs, failed, oc = parse_cv_entries(publications_section(read_cv_text('data/inputs/fels-cv.docx')))
print(len(pubs), 'deterministic /', len(oc), 'entries')"
```

## Conventions

- **Deterministic first, LLM last.** CV entries are parsed with heuristics; only
  failures go to the LLM, one entry per call. Every entry's outcome (path,
  failed fields, CV section) is recorded by `ParseTracker` (`src/metrics.py`)
  to `state/parse-report.jsonl` + `state/parse-summary.jsonl` — use these to
  tune `cv_parse.py` heuristics. Parsing must be *conservative*: a wrong parse
  that validates is worse than a failure that falls to the LLM.
- **Model:** `google/gemini-3-flash-preview` via OpenRouter (cheap, 1M ctx).
  Overridable with `OPENROUTER_MODEL`. Goal: the *lightest* agent that can do
  the task — output tokens are capped per call and every LLM call is tagged
  with a stage label and recorded (`src/metrics.py`).
- **Supabase is the contract.** Backend writes with the secret key; frontend
  reads with the publishable key under RLS. Don't add a write path to the browser.
- **Don't trust the LLM blindly.** Deterministic slugs + Pydantic validation +
  one repair retry. `hct-manager qa` audits what the AI wrote.
- **Scholar is opt-in.** Never hit scholar.google.* in tests or default runs;
  Scholar sources are `enabled: false` in sources.yaml and gated by
  `Config.scholar_enabled`.
- **ujin is a black box.** No Scholar-specific parsing inside it.
- Every Python module has unit tests; the LLM and network are always mocked
  (httpx `MockTransport` / fakes). No live calls in the suite.
- Package is imported as `src` (e.g. `from src.config import Config`); run with
  `PYTHONPATH=.` from `backend/`.
