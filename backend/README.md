# hct-manager

Generates the HCT Lab site's data into **Supabase**. One-shot pipeline:

1. read `sources.yaml` (Google Scholar profiles to watch);
2. scrape each via the **ujin** scrape service;
3. skip sources whose content fingerprint is unchanged;
4. ask an LLM (Gemini 3 Flash via OpenRouter) to extract structured papers;
5. validate with Pydantic and upsert to the `publications` table, then rebuild
   the `timeline` (5 most recent). `migrate-content` fills `people`/`research`/
   `site_content` from the static page.

The frontend reads those tables directly with the publishable key. See
`docs/FRONTEND-DB.md` and `docs/ARCHITECTURE.md` for the full picture.

## Commands

```bash
hct-manager run [--force]        # scrape + extract + upsert publications + timeline
hct-manager import-html [--max-chars N] [--no-timeline] [--no-blurbs]
                                 # publications from the static page (when Scholar is blocked)
hct-manager migrate-content [--no-ai]   # static HTML -> people/research/site_content
hct-manager analyze-style FILE [--save]   # short style profile of a document
hct-manager describe [--all] [--fetch] [--limit N]   # write lab-voice descriptions
hct-manager qa [--out PATH] [--no-source-check] [--strict]   # QA the live Supabase data
hct-manager health               # check the ujin scrape service
```

## Configuration (env)

| Variable                 | Default                              | Purpose                          |
| ------------------------ | ------------------------------------ | -------------------------------- |
| `OPENROUTER_API_KEY`     | — (required)                         | OpenRouter auth                  |
| `OPENROUTER_MODEL`       | `google/gemini-3-flash-preview`      | LLM model                        |
| `SB_URL`                 | — (required)                         | Supabase project URL             |
| `SB_SEC_KEY`             | — (or `SB_SERVICE_ROLE_KEY`)         | secret key — backend writes      |
| `SB_PUB_KEY`             | — (or `SB_ANON_PUB_KEY`)             | publishable key — for the frontend |
| `UJIN_URL`               | `http://ujin:8901`                   | ujin scrape service base URL     |
| `HCT_DATA_DIR`         | `backend/data`                     | sources/templates/state/…        |
| `HCT_INDEX_HTML`         | `frontend/index.html`                | static page parsed by migrate-content |
| `HCT_SCRAPE_MODE`        | `article`                            | default ujin scrape mode         |

## Tests

```bash
pip install -e ".[dev]" && pytest      # or: PYTHONPATH=. pytest
```
