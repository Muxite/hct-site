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
  server-side, so a routine resync can't clobber a value an admin sets
  directly through the browser CMS (once built) **for exactly this field
  set**. This applies to the CLI/automated resync path only — `viewer.py`'s
  own edit/add/delete routes push straight to Supabase with a forced
  single-row write (see `_push_yaml_edit` et al. in `viewer.py`), so an
  explicit maintainer edit through that tool always lands, `tagline`
  included.
- **Known gap: `people.kind` (current/alumni status) is NOT in the
  fill-if-empty set**, unlike the fields above — `sync_content.py`'s
  `_PEOPLE_FILL_FIELDS` always force-upserts it from `people.yaml`, matching
  its role as the YAML's own way to flip someone to alumni via a bulk resync.
  But the admin-CMS plan (`docs/superpowers/plans/...` Task 7) has Sidney
  toggle current/alumni status directly in the browser too — once that ships,
  a routine `sync-content` run could silently revert his toggle back to
  whatever `people.yaml` currently says. Adding `kind` to the fill-if-empty
  set isn't a clean fix either: it would break `people.yaml`'s own
  bulk-flip-to-alumni workflow for anyone already synced once. Unresolved;
  whoever builds the CMS's status toggle should either accept this as a
  known limitation (document it in the admin UI) or design a real
  reconciliation mechanism (e.g. an explicit "last changed by" marker) before
  relying on it.
- **Delete propagation is asymmetric between `research` and `people`**:
  `hct-manager sync-content`'s bulk resync deletes a `research` slug that's no
  longer in `research.yaml`/`projects.yaml` (YAML is the *only* way a project
  is ever created, so removing an entry and re-syncing is unambiguous
  curation) — but it never deletes a `people` row just because their name is
  absent from `people.yaml`. That's deliberate: the admin CMS can insert a
  person directly, bypassing `people.yaml` entirely, and that person is
  absent from the YAML by construction; if the bulk sync deleted on that
  basis, the very next routine `sync-content` run would silently undo the
  admin's add. Deliberate person deletion still works, just always as an
  explicit single-row action — `viewer.py`'s forced delete (for YAML-sourced
  people) or the CMS's own `deletePerson` call — never as a side effect of
  "remove them from `people.yaml` and re-run sync-content."
