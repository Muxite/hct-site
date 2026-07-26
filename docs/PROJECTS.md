# PROJECTS.md — project-centric restructure

Restructures the site around **projects**: a curated, featured layer on top of
the full publication history. A project has a hero image, a project-level
summary, the lab **people** involved, and its **member papers**. Each featured
paper carries three audience-targeted summaries and a representative image.
Papers that don't belong to a featured project still appear in the full
publication timeline exactly as they do today.

This note is the source of truth for the change; edit it as decisions evolve.

## Decisions (locked)

| Question | Choice |
| --- | --- |
| Paper ↔ project cardinality | **One project per paper** (`publications.project_slug`, nullable). |
| How papers are grouped | **AI-suggested, human-reviewed** — clustering emits `projects.yaml`, you edit it; the YAML is the source of truth. |
| Representative images | **Pulled from paper figures** (render the OA/canonical PDF, extract a figure), degrading to project hero → generated placeholder. |
| Homepage | **Projects lead**; the full publication timeline stays below and catches every non-project paper. |

## Audience → summary style

The three promoted styles come from the existing `paper_samples` A–E bake-off:

| Style | Name | Audience | Placement on a paper page |
| --- | --- | --- | --- |
| **A** | Plain-language explainer | General public | Body (primary) |
| **B** | Technical abstract | Researchers | Expandable / linked |
| **C** | Problem / Approach / Result | Prospective grad students | Expandable / linked |

## Data model

### `publications` (add columns)
- `project_slug text` — the paper's single owning project (nullable; most
  historical papers stay null and only appear in the timeline).
- `summary_plain text` — promoted style A.
- `summary_abstract text` — promoted style B.
- `summary_par text` — promoted style C.
- `image text` — path/URL of the extracted figure.

`description` (the existing single lab-voice blurb) is kept for backward compat
and retired once `summary_plain` is populated everywhere.

### `research` → project fields (extend in place; table keeps its name)
- `slug text unique` — stable project key (deterministic slug of the title).
- `summary text` — longer than `tagline`, the project-page body.
- `hero_image text` — project hero image.

Existing `research` columns (`title`, `tagline`, `description`, `link`,
`image`, `kind`, `sort_order`) stay. `kind` still means `current | archived`.

### `project_people` (new join table)
People stay in `people`; this links them per project. People **can** be on
multiple projects (many-to-many), even though papers can't.

```
project_people (
  project_slug text,        -- -> research.slug
  person_name  text,        -- -> people.name (loose ref)
  role_on_project text,     -- e.g. "lead", "collaborator" (optional)
  sort_order   int
)
```

No `project_papers` table — `publications.project_slug` carries that edge.

### `projects.yaml` (new, editable, in dropbox)

The source of truth for groupings. AI clustering proposes it; you review/edit.

```yaml
projects:
  - title: Brain2Speech
    slug: brain2speech            # optional; derived from title if omitted
    tagline: BCIs + 3D articulatory speech synthesis
    summary: |
      Longer project-page body...
    hero_image: assets/img/b2s.png
    status: current               # current | archived
    people:                       # names -> project_people
      - name: Sidney Fels
        role: lead
      - name: Some Student
    papers:                       # paper slugs -> publications.project_slug
      - fels2022-brain-to-speech
      - fels2021-articulatory-synth
```

`sync-content` reads this, upserts the `research`/project rows + `project_people`,
and stamps `project_slug` onto the listed publications (clearing it from papers
no longer listed).

## Backend pipeline

1. **`src/cluster.py` (new)** — feeds all publications to the LLM, returns
   candidate projects (title, member slugs, suggested people), writes
   `dropbox/projects.yaml` for review. Gated by the API key (waits until it's
   re-enabled). Deterministic-first: AI only *proposes*; the YAML is truth.
2. **`src/figures.py` (new)** — for each paper with an OA/canonical URL (already
   resolved by `paper_samples.py`), render the PDF with **PyMuPDF** and extract
   the largest/first figure, upload to a **Supabase Storage** bucket, set
   `publications.image`. Best-effort per paper; fallbacks: paper figure →
   project hero → generated gradient placeholder. Highest failure rate, so it
   degrades gracefully and never blocks a run.
3. **Summary promotion** — reuse the `paper_samples` A/B/C generation, but write
   the three chosen styles onto `publications` instead of the disposable
   experiment table.
4. **`sync-content` extension** — read `projects.yaml` → upsert project rows +
   `project_people`, stamp `project_slug` onto publications.

## Frontend

- **Router**: lightweight hash router (no new heavy dep, works on static
  hosting) — replaces the `?samples` query-param hack.
- **Home** (`/`): lab intro → **project grid** (hero image + summary) → full
  publication timeline below (unchanged).
- **Project page** (`/projects/:slug`): hero, summary, people-involved tiles
  (reuse People), member-paper list (small image + A summary + link).
- **Paper page** (`/papers/:slug`): image, **A as the body**, expandable **B**
  and **C**, authors / venue / DOI.

## Rollout order

Sequenced so all the no-API work lands first (the key is off):

1. **Schema + `projects.yaml` shape + `sync-content`** — relational structure
   live with manual/empty summaries. No AI, no images.
2. **Frontend routing + project/paper pages** against that structure.
3. **AI clustering + A/B/C promotion** — when the key is re-enabled.
4. **Figure extraction** — last; highest failure rate, degrade gracefully.

## Open / defaulted

- **Figure storage**: Supabase Storage bucket, public read, backend writes
  (consistent with "Supabase is the contract").
- **`description` retirement**: kept until `summary_plain` is populated
  everywhere, then dropped.
- **`hct-manager sync-content`'s *bulk* resync is fill-if-empty for
  `tagline`/`summary`/`hero_image`** (and the analogous `people`
  `role`/`email`/`photo`/`bio`): a routine re-sync of `people.yaml`/
  `research.yaml`/`projects.yaml` only sets these once they're still null
  server-side, so it can never clobber a value an admin sets directly through
  a future browser CMS. This applies to the CLI/automated resync path only —
  `viewer.py`'s own edit/add/delete routes push straight to Supabase with a
  forced single-row write (see `_push_yaml_edit` et al. in `viewer.py`), so an
  explicit maintainer edit through that tool always lands, `tagline` included.
