# HCT Site

This project keeps the HCT Lab website up to date on its own. It reads the
lab's **CV document** (a `.docx` you drop into the `dropbox/` folder), parses
its publication list — with plain rules first and an AI model only for the
entries the rules can't handle — and saves everything into a **database
(Supabase)**. The website reads that database directly, so the frontend just
needs the project URL and a read-only key — see
[`docs/FRONTEND-DB.md`](docs/FRONTEND-DB.md).

You don't have to keep anything running. You turn it on when you want to check
for new papers, it updates the database if something changed, and then it stops.

> ### 👩‍💻 Building the website? Start here
> You don't need this repo or any of the backend. All the content lives in
> Supabase and you read it with one URL + one public key, from **any** stack
> (plain JS, React/Next, Vue, Svelte, or just `fetch`). Everything you need —
> connection values, table columns, and copy-paste query examples — is in
> **[`docs/FRONTEND-DB.md`](docs/FRONTEND-DB.md)**.

## How it works (in plain words)

```
CV (.docx in dropbox/)  →  (rule-based parse, AI only for stragglers)  →  Supabase  →  website
```

1. **Drop the CV in** — put the updated CV into `dropbox/` (mounted into the
   container at `/app/data/inbox`).
2. **Notice changes** — if the file is byte-identical to last time, we stop
   there and don't waste any work.
3. **Parse** — the publications section is split into entries and each entry
   is parsed with plain rules (authors, year, title, venue). Only the entries
   the rules can't handle confidently go to an AI model (Gemini 3 Flash), one
   tiny call per entry. A parse report shows how often that happens and where.
4. **Check it** — every result is validated, so a mistake (rule or AI) can't
   put bad data on the site.
5. **Publish** — papers are written to the `publications` table, and the
   `timeline` is rebuilt as the **full publication history** (newest first).
   `sync-content` fills `people` and `research` from two editable YAML files
   (with current/alumni/archived status) and `site_content` (header/nav + the
   prose sections) from a third, `site.yaml`.
6. **Show** — the website (a React + Vite app under `frontend/`) reads those
   tables and draws each section: the year-grouped timeline as the centerpiece,
   current people/projects first, alumni and past projects in their own groups.

> Google Scholar can still be used as a *secondary* source, but it is **off by
> default** (Scholar blocks bots aggressively). Opt in per run with
> `HCT_SCHOLAR_ENABLED=1`; on a paper found in both, the CV's version wins.

## Folder layout

```
docker-compose.yml      starts the data pipeline (ujin + hct-manager)
.env.example            copy to .env and add your OpenRouter + Supabase keys
frontend/               the website — a React + Vite app that reads Supabase
  src/                  components, data layer, styles (its own .env: VITE_SB_*)
backend/
  ujin/                 the scraper service (a git submodule)
  pyproject.toml        the Python package metadata
  Dockerfile
  src/                  the program that scrapes + asks the AI + writes to Supabase
  tests/                unit tests (LLM + network always mocked)
  data/                 settings: which people to check, prompts, examples, saved state
db/schema.sql           the database schema (tables + row-level security)
docs/ARCHITECTURE.md    how the pieces fit together
docs/FRONTEND-DB.md     what the frontend needs to read the database
```

## Run it

You need Docker, an [OpenRouter](https://openrouter.ai/) API key, and a
[Supabase](https://supabase.com/) project.

```bash
# 1. Add your keys (OpenRouter + Supabase URL/keys)
cp .env.example .env        # then edit .env and paste your keys

# 2. Create the database tables (one time): paste db/schema.sql
#    into the Supabase SQL editor (or apply it with the Supabase CLI/MCP).

# 3. Start the scraper service (compose lives at the repo root)
docker compose up -d ujin

# 4. Drop the lab CV into the drop folder (any time it's updated)
cp ~/Downloads/fels-cv.docx dropbox/

# 5. Update the publications (run this whenever the CV changed)
docker compose run --rm hct-manager run
#   add --force to rebuild even if nothing changed:
docker compose run --rm hct-manager run --force

# 6. Sync people + research + site boilerplate (edit the YAML, re-run any time)
#    people.yaml / research.yaml / site.yaml live in dropbox/ (or backend/data/inputs/)
docker compose run --rm hct-manager sync-content
```

Then run the website. It reads Supabase directly with the publishable key:

```bash
cd frontend
cp .env.example .env        # set VITE_SB_URL + VITE_SB_PUBLISHABLE_KEY
npm install
npm run dev                 # local dev server
npm run build               # production build -> frontend/dist/
```

> **Google Scholar note:** Scholar is an optional secondary source and is
> **disabled by default** — Scholar blocks bots, and the CV already carries
> everything. To opt in for one run (uses the headless-browser scraper):
> ```bash
> docker compose --profile render up -d ujin-render
> docker compose run --rm -e UJIN_URL=http://ujin-render:8901 -e HCT_SCHOLAR_ENABLED=1 hct-manager run
> ```
> On papers found in both sources, the CV's metadata wins.

## Who's in the lab / what's current / the page copy

Edit `dropbox/people.yaml`, `dropbox/research.yaml`, and `dropbox/site.yaml`
(start from the committed defaults in `backend/data/inputs/`). People and
research entries have a `status:` — `current` or `alumni` for people, `current`
or `archived` for research projects — and the site groups them accordingly.
`site.yaml` holds the masthead (title/subtitle/tagline/nav) and the editable
prose sections (vision, innovation, contact, EDI, …). Then run `sync-content`
(step 6 above). Photos go in `frontend/public/assets/` referenced as
`/assets/<file>` (see that folder's README).

## Which sources to read

Edit `backend/data/sources/sources.yaml` to add or change publication sources —
CV files (primary) and, optionally, Scholar profiles (off by default).

## Match the lab's writing voice (optional)

You can give the AI a sample of the lab's writing so any descriptions it writes
sound right:

```bash
docker compose run --rm hct-manager analyze-style /app/data/inputs/fels-cv.docx --save
```

Then write a short blurb under each paper (only the ones missing one). Add
`--fetch` to scrape each paper's own page for grounding, or `--all` to redo
every entry:

```bash
docker compose run --rm hct-manager describe --fetch
```

## Developing

Backend (Python) tests:

```bash
cd backend && PYTHONPATH=. pytest
```

Frontend (React + Vite):

```bash
cd frontend && npm test     # pure-helper unit tests (node --test)
```

## What's next

The data lives in Supabase and the website reads it directly with a read-only
key. Natural next steps: scheduled (weekly) runs instead of manual, AI-written
`people` bios, real photo assets, and deploying the Vite build. See
`frontend/README.md`, `docs/ARCHITECTURE.md`, and `docs/FRONTEND-DB.md`.
