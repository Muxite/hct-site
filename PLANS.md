# HCT Site — Plans & Architecture

A small, containerized service that keeps the HCT Lab website's **Publications**
section up to date automatically. It scrapes the lab members' Google Scholar
profiles, uses an LLM to turn the raw page into clean structured data, stores
that data as **YAML**, and renders the website's HTML **from that YAML**.

The design goal is that the backend can be **off most of the time**: turn it on
(manually, or weekly later), let it check for changes, regenerate files if
anything changed, then shut down. Nothing needs to stay running.

---

## 1. Current scope vs. future

| Concern            | Now (this build)                                   | Future                                  |
| ------------------ | -------------------------------------------------- | --------------------------------------- |
| Data store         | **YAML files on disk** (`frontend/data/*.yaml`)    | Supabase / Postgres                     |
| Frontend reads     | Static HTML rendered from YAML at build time       | Frontend queries Supabase REST directly |
| Polling            | **Manual, one-shot** (run when told)               | Scheduled (weekly), adaptive via ujin   |
| Backend uptime     | Run-to-completion, then exit                        | Wake → check → maybe regen → sleep      |

> **Decision (locked):** Do **not** build Supabase yet. The hct-manager writes
> directly to YAML, and we generate HTML from YAML. Supabase is the eventual
> target but is explicitly out of scope for this build.

---

## 2. Components

Two containers, brought up via `docker compose` in `backend/`.

### 2.1 `ujin` scraper container

- Built from the `backend/ujin` git submodule (tracks `Muxite/ujin` master,
  which now includes the rich scrape service + bundled `obscura` headless
  renderer for JS-heavy / bot-protected pages like Google Scholar).
- Runs `ujin scrape-serve` → FastAPI on **:8901**.
- Relevant endpoints (already provided by ujin):
  - `POST /scrape` — `{url, mode, force_refresh, ...}` → `ScrapeResponse`
    with `text` / `links`, a stable **`fingerprint`** (SHA-256 of normalized
    payload), `used_renderer`, `strategy_used`, caching info.
  - `POST /scrape:batch`, `GET /health`, `GET /metrics`.
- hct-manager talks to it over HTTP on the compose network. We treat ujin as a
  black box — we do **not** add Scholar-specific parsing inside ujin; ujin just
  fetches + renders the page, the LLM does the parsing.

### 2.2 `hct-manager` container (the thing we build)

A small Python app. Responsibilities:

1. **Read sources** — a list of profiles/pages to watch (`assets/sources/`).
2. **Scrape** each via the ujin container (`/scrape`, obscura render on).
3. **Change detection** — compare each source's `fingerprint` against the last
   stored one (`assets/state/`). Skip the LLM entirely if nothing changed.
4. **LLM extraction** — for changed sources, send the rendered page text to an
   LLM (OpenRouter, key from `keys.env`) with a prompt that returns
   **structured per-paper data**. Validate against a **Pydantic** model; if the
   LLM produces bad types, validation catches it and we retry/repair.
5. **Write YAML** — emit `frontend/data/publications.yaml` (per-paper blocks:
   quick overview fields always, optional long `description`). This is the only
   output hct-manager produces for the site.
6. **Style analysis (separate capability)** — read an input document
   (e.g. `assets/inputs/fels-cv.docx`) and produce a **short but detailed LLM
   analysis of its writing style**, stored in `assets/`. This style profile is
   fed into the generation prompt so generated descriptions match the lab's
   voice.

The whole thing is **one-shot**: `hct-manager run` does steps 1–5 once and
exits. A `--force` flag bypasses fingerprint short-circuiting.

### 2.3 `hct-render` (frontend, client-side JS)

Rendering is **not** done by hct-manager. The browser does it:

- `frontend/index.html` loads `js-yaml` + the `hct-render/renderers/` scripts.
- On load, hct-render **fetches `data/publications.yaml`**, parses it, and
  renders the Publications entries into the `#publications` section (replacing
  the static placeholder markup).
- This mirrors the future Supabase pattern exactly — later we swap the
  "fetch YAML" call for a "query Supabase" call and the renderer is unchanged.

So `publications.yaml` is the contract between the Python generator and the JS
renderer; the site is static files served as-is.

---

## 3. Data flow

```
  GENERATE (Python, backend, one-shot, manual trigger)
                               |
                               v
   sources.yaml  ──►  hct-manager  ──HTTP──►  ujin /scrape  ──►  (obscura render)
   (Scholar URLs)         |                       |
                          | fingerprint           └─ rendered page text + fingerprint
                          v
                  assets/state/<src>.json   ── changed? ──┐ no ──► stop (nothing to do)
                          |                                │
                          | yes                            │
                          v                                │
                  LLM (OpenRouter)  +  style profile  ◄────┘
                          |
                          v
                  Pydantic validation
                          |
                          v
            frontend/data/publications.yaml   ◄── the contract ──┐
                                                                  │
  RENDER (JS, browser, on page load)                             │
            frontend/index.html  ──fetch──►  data/publications.yaml
                          |
                          v
            hct-render renders the #publications section in the DOM
```

No database in the loop. The YAML is the contract between "the part that
generates data" and "the part that renders the site." Later, the YAML write +
HTML render get replaced by a Supabase write + frontend query, but the schema
stays the same.

---

## 4. Data schema (Pydantic → YAML)

`publications.yaml` is organized **per paper** so the page has a quick overview
but each entry can carry an optional longer description.

```yaml
generated_at: 2026-06-02T00:00:00Z
source_fingerprints:
  fels: "3f9a1c8b…"
  ashjaee: "a7c0d2e8…"
publications:
  - id: zhu2022-unified-control-logic   # stable slug, used for dedupe
    title: "A unified representation of control logic in human-ultrasound machine interaction"
    authors:                            # ordered list
      - "Hongzhi Zhu"
      - "Yasmin Halwani"
      - "Robert Rohling"
      - "Sidney Fels"
      - "Septimiu Salcudean"
    venue: "IEEE Journal of Biomedical and Health Informatics"
    year: 2022
    type: article                       # article | inproceedings | preprint | …
    link: "https://doi.org/10.1109/JBHI.2022.3150242"   # optional
    bibtex: null                         # optional
    description: null                    # optional, LLM-written, lab style
```

Pydantic models (in hct-manager):

- `Publication` — fields above, with validators (year is int, type is an enum,
  authors non-empty, link is a URL or null).
- `PublicationSet` — `generated_at`, `source_fingerprints`, `publications: list[Publication]`.

The LLM is asked to emit JSON matching `PublicationSet`; we parse → validate →
dump to YAML. Validation failure ⇒ one repair retry, then hard fail with a
clear message.

---

## 5. Asset layout (volume-mounted into hct-manager)

```
backend/assets/
  sources/      sources.yaml — the list of profiles to watch (Scholar URLs)
  templates/    prompt templates (extraction prompt, style-analysis prompt) +
                the HTML fragment template for a publication entry
  examples/     few-shot examples for the LLM (good extractions, good descriptions)
  inputs/       raw style inputs (fels-cv.docx, …)
  state/        per-source fingerprints + last LLM output (change detection)
```

`frontend/`:

```
frontend/
  index.html               the site (Publications section gets replaced)
  data/                    publications.yaml — generated source of truth
  hct-render/renderers/    YAML → HTML renderer(s)
```

---

## 6. Configuration & secrets

- `keys.env` (gitignored) — `OPENROUTER_API_KEY`. `keys.env.example` documents it.
- `sources/sources.yaml` — which URLs to scrape and which member they map to.
- LLM model + base URL configurable via env. **Default model: Claude Sonnet**
  via OpenRouter (`OPENROUTER_MODEL`, default `anthropic/claude-sonnet-4.6`).
- ujin URL configurable (default `http://ujin:8901` on the compose network).

---

## 7. Milestones (build order)

1. **M1 — schema + YAML I/O.** Pydantic models, load/dump `publications.yaml`,
   round-trip tests. *(no network, no LLM)*
2. **M2 — renderer (frontend JS).** `hct-render/renderers/`: fetch
   `data/publications.yaml`, render entries into the `#publications` section on
   page load. Pure client-side; data source pluggable (YAML now, Supabase later).
3. **M3 — ujin client.** Thin HTTP client for `/scrape`; fingerprint storage +
   change detection in `assets/state/`. Tested against a fake server.
4. **M4 — LLM extraction.** Prompt + OpenRouter call → `PublicationSet`;
   validation + one repair retry. Tested with a recorded page fixture + mocked LLM.
5. **M5 — style analysis.** Read input doc → short style profile; wire into the
   generation prompt. Mocked-LLM tests.
6. **M6 — orchestration + CLI.** `hct-manager run [--force]` ties M3→M4→M1→M2
   together; one-shot, exits. End-to-end test with everything mocked.
7. **M7 — containerize.** `Dockerfile` for hct-manager, `docker-compose.yml`
   bringing up `ujin` + `hct-manager`, volume mounts for assets + frontend.
8. **M8 — docs.** Simple-language `README.md`, this `PLANS.md`, architecture
   notes in `docs/`.

Every code file gets unit tests (per the brief). Network + LLM are always
mocked in tests; no live calls in CI.

---

## 8. Explicit non-goals (for now)

- No Supabase / database.
- No scheduled or adaptive polling — manual one-shot only.
- No auth, no write API — the frontend is static files.
- No edits to ujin internals — it's a black-box submodule dependency.
