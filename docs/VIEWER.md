# Local data viewer

`hct-manager viewer` serves a small **localhost admin viewer** over the five
Supabase tables the agent writes (`publications`, `timeline`, `people`,
`research`, `site_content`). It is **not** the public site — it's a
server-rendered, SQL-style view (one page per table, columns mirroring
`db/schema.sql`) for eyeballing and lightly editing what the system produced.

## Run it

```bash
cd backend
pip install -e .[viewer]          # adds FastAPI + uvicorn (kept out of core deps)
hct-manager viewer                # http://127.0.0.1:8080
hct-manager viewer --port 9000    # or pick a port
```

It reads with the **secret** key (same env as the rest of the backend:
`SB_URL` + `SB_SEC_KEY`, plus `OPENROUTER_API_KEY` since it builds the normal
`Config`). Bind stays on `127.0.0.1` by default — it's an admin tool, not a
public endpoint.

## Pages

- **Overview** (`/`) — every table with its live row count and edit mode.
- **Table** (`/t/<table>`) — all rows, columns in schema order; JSON columns
  (`authors`, `value`) are pretty-printed. Editable rows have an **edit** link;
  `people`/`research` also have **add** / **del**.

## Editing — where writes go

The viewer respects the project's "YAML is the source of truth" rule, so an edit
never gets silently clobbered by the next sync:

| table | editable fields | write path |
|---|---|---|
| `people` | name, role, email, photo, kind | rewrite `people.yaml` → re-sync both tables |
| `research` | title, tagline, link, image, kind | rewrite `research.yaml` → re-sync both tables |
| `site_content` | `value` (edited as JSON) | rewrite `site.yaml` → upsert `site_content` |
| `publications` | description, venue, link, bibtex | upsert straight to Supabase (`on_conflict=slug`) |
| `timeline` | blurb, date_label | upsert straight to Supabase (`on_conflict=position`) |

- **YAML-backed** edits (`people`/`research`/`site_content`) are written back to
  the file in `data/inputs/` (or the mounted `inbox/`), preserving the file's
  comment header, then pushed to Supabase via the existing
  `sync_content` / `load_site_yaml` path. So the viewer and `hct-manager
  sync-content` always produce identical DB state.
- **Generated** edits (`publications`/`timeline`) go straight to Supabase. Heads
  up: a later `hct-manager describe --all` or `hct-manager run` can overwrite
  these (e.g. a regenerated `description`). Durable copy edits belong in the
  source CV / templates, not here.

All writes are validated through the same Pydantic models (`Person`,
`ResearchProject`, `Publication`, `TimelineEntry`) and YAML status checks, so a
bad edit re-renders the form with the error and writes nothing.

## Tests

`tests/test_viewer.py` drives the app with FastAPI's `TestClient`, a fake
Supabase client, and temp YAML files — no network, same as the rest of the
suite. The
YAML round-trip (`load → dump → load` is identity, header preserved) is covered
in `tests/test_sync_content.py` and `tests/test_content.py`.
