# hct-manager

Generates the HCT Lab site's data into **Supabase**. One-shot pipeline:

1. read `sources.yaml` (CV files first; optional Scholar profiles, disabled by
   default — `HCT_SCHOLAR_ENABLED=1` to opt in);
2. read each CV off disk (a same-named file in the `inbox/` drop folder wins);
   scrape any enabled URLs via the **ujin** scrape service;
3. skip sources whose content fingerprint is unchanged;
4. parse CV entries **deterministically** (`src/cv_parse.py`); only entries the
   heuristics can't fill go to an LLM (Gemini 3 Flash via OpenRouter), one
   entry per call — every outcome lands in `state/parse-report.jsonl`;
5. validate with Pydantic and upsert to the `publications` table (the CV wins
   on duplicate slugs), then rebuild the `timeline` as the **full publication
   history** (newest first). `sync-content` fills `people`/`research` from
   editable YAML (with current/alumni/archived status) and `site_content`
   (header/nav + prose sections) from `site.yaml`.

The frontend reads those tables directly with the publishable key. See
`docs/FRONTEND-DB.md` and `docs/ARCHITECTURE.md` for the full picture.

## Commands

```bash
hct-manager run [--force]        # CV parse (+ optional Scholar) + upsert publications + full timeline
hct-manager sync-content [--people PATH] [--research PATH] [--site PATH]
                                 # people.yaml/research.yaml/site.yaml -> Supabase
hct-manager analyze-style FILE [--save]   # short style profile of a document
hct-manager describe [--all] [--fetch] [--limit N]   # write lab-voice descriptions
hct-manager qa [--out PATH] [--no-source-check] [--strict]   # QA the live Supabase data
hct-manager health               # check the ujin scrape service
```

`site.yaml` shape (committed default in `data/inputs/`, overridable from the
`inbox/` drop folder):

```yaml
site:                       # -> site_content key "site_meta"
  title: HCT Lab
  subtitle: Human Communication Technologies Lab
  tagline: ...
  nav: [Latest, Vision, People, Research, Contact]
sections:                   # -> one site_content key each ({title, text})
  vision: { title: Vision, text: "..." }
  contact: { title: Contact, text: "..." }
  # ... innovation, land_acknowledgment, edi, sponsors, opportunities
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
| `HCT_DATA_DIR`         | `backend/data`                     | sources/templates/state/inputs/inbox |
| `HCT_INDEX_HTML`         | unset                                | optional: a *rendered* static page for the legacy QA cross-check |
| `HCT_SCRAPE_MODE`        | `article`                            | default ujin scrape mode         |
| `HCT_SCHOLAR_ENABLED`    | unset (off)                          | opt-in switch for Scholar sources |

## Tests

```bash
pip install -e ".[dev]" && pytest      # or: PYTHONPATH=. pytest
```
