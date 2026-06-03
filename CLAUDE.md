# CLAUDE.md — HCT Site

Auto-updates the HCT Lab website. Scrapes lab members' Google Scholar pages (via
the **ujin** submodule), an LLM extracts/writes structured data, and everything
is written to **Supabase** (the single source of truth). The frontend reads
Supabase directly with a publishable key.

## Layout

```
docker-compose.yml     ujin + one-shot hct-manager (run from repo root)
.env / .env.example    OPENROUTER_API_KEY + SB_* (gitignored)
db/schema.sql          Supabase tables + RLS
docs/                  ARCHITECTURE.md, FRONTEND-DB.md
frontend/              index.html + hct-render/ (browser ES modules, read DB)
backend/
  pyproject.toml       package metadata (package name: src)
  Dockerfile
  src/                 the Python agent (cli, config, llm, extract, describe,
                       timeline, content, orchestrate, qa, metrics, ...)
  tests/               unit tests — LLM + network ALWAYS mocked
  data/                sources/ templates/ inputs/ state/  (mounted into the container)
  ujin/                scraper service (git submodule; black box, do not edit)
experiments/           agent performance harness + plots (token/error/hallucination)
```

## Commands

```bash
# Python tests (from backend/)
cd backend && PYTHONPATH=. pytest

# CLI (installed entry point `hct-manager`, or `python3 -m src.cli`)
hct-manager run [--force]        # scrape -> extract -> upsert publications + timeline
hct-manager import-html          # publications from the static page (Scholar blocked)
hct-manager migrate-content      # static HTML -> people/research/site_content
hct-manager describe --fetch     # per-paper lab-voice description (shortened from source)
hct-manager qa                   # QA report on the live Supabase data
hct-manager health               # check the ujin scrape service

# Frontend renderer tests
cd frontend/hct-render && npm test
```

## Conventions

- **Model:** `google/gemini-3-flash-preview` via OpenRouter (cheap, 1M ctx).
  Overridable with `OPENROUTER_MODEL`. Goal for this branch: the *lightest*
  agent that can do the task — output tokens are capped per call and every LLM
  call is tagged with a stage label and recorded (`src/metrics.py`).
- **Supabase is the contract.** Backend writes with the secret key; frontend
  reads with the publishable key under RLS. Don't add a write path to the browser.
- **Don't trust the LLM blindly.** Deterministic slugs + Pydantic validation +
  one repair retry. `hct-manager qa` audits what the AI wrote.
- **ujin is a black box.** No Scholar-specific parsing inside it.
- Every Python module has unit tests; the LLM and network are always mocked
  (httpx `MockTransport` / fakes). No live calls in the suite.
- Package is imported as `src` (e.g. `from src.config import Config`); run with
  `PYTHONPATH=.` from `backend/`.
