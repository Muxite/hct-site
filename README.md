# HCT Site

This project keeps the HCT Lab website up to date on its own. It looks at the
lab members' Google Scholar pages, uses an AI model to turn each page into a tidy
list of papers, and saves everything into a **database (Supabase)**. The website
reads that database directly, so the frontend just needs the project URL and a
read-only key — see [`docs/FRONTEND-DB.md`](docs/FRONTEND-DB.md).

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
Google Scholar pages  →  (scrape)  →  (AI reads it)  →  Supabase  →  website reads it
```

1. **Scrape** — a small service called *ujin* fetches the Scholar pages.
2. **Notice changes** — if a page looks exactly the same as last time, we stop
   there and don't waste an AI call.
3. **AI extract** — for pages that changed, an AI model (Gemini 3 Flash) reads
   the page and writes out each paper's title, authors, year, venue, and link.
4. **Check it** — the result is validated, so a mistake from the AI can't put
   bad data on the site.
5. **Publish** — papers are written to the `publications` table, plus a small
   `timeline` of the 5 most recent. `migrate-content` fills `people`, `research`,
   and `site_content` from the existing page.
6. **Show** — when someone opens the website, it reads those tables and draws
   each section.

## Folder layout

```
docker-compose.yml      starts everything (ujin + hct-manager)
.env.example            copy to .env and add your OpenRouter + Supabase keys
frontend/
  index.html            the website (reads its data from Supabase)
  hct-render/           browser code that queries the DB and draws each section
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

# 4. Update the publications (run this whenever you want to check for new papers)
docker compose run --rm hct-manager run
#   add --force to rebuild even if nothing changed:
docker compose run --rm hct-manager run --force

# 5. One time: import the rest of the page (people, research, section text)
docker compose run --rm hct-manager migrate-content
```

Put your project URL + **publishable** key in `frontend/hct-render/config.js`,
then open `frontend/index.html` in a browser to see the result.

> **Google Scholar note:** Scholar tries to block bots. The fast default
> scraper may get blocked. If that happens, use the heavier scraper that runs a
> real headless browser (slower to build the first time):
> ```bash
> docker compose --profile render up -d ujin-render
> docker compose run --rm -e UJIN_URL=http://ujin-render:8901 hct-manager run
> ```
> If Scholar is blocked entirely (e.g. a datacenter IP), populate publications
> from the page's own list instead — no scraper needed:
> ```bash
> docker compose run --rm hct-manager import-html
> ```
> It reads the most recent entries from `frontend/index.html`, writes them to the
> `publications` table, and rebuilds the `timeline`.

## Who to track

Edit `backend/data/sources/sources.yaml` to add or change the people whose
Scholar pages get checked.

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

Frontend (renderer) tests:

```bash
cd frontend/hct-render && npm test
```

## What's next

The data lives in Supabase and the website reads it directly with a read-only
key. Natural next steps: scheduled (weekly) runs instead of manual, AI-written
`people` bios, and richer `site_content`. See `docs/ARCHITECTURE.md` and
`docs/FRONTEND-DB.md`.
