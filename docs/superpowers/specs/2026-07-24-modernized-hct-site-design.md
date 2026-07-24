# Modernized, content-complete HCT site — design

**Date:** 2026-07-24
**Status:** approved (brainstorm), pending implementation plan
**Branch:** `feat/variants-gallery`

## Goal

Turn the default modern homepage into a *modernized version of the old HCT
site that demonstrates everything Sidney Fels put on it* — vision, values,
sponsors, opportunities, people, projects (including the historical archive),
and the full publication record — while **keeping the technical feel** of the
existing redesign and **not over-designing** (no bespoke rebuild, no throwing
away the four-look switcher).

This is driven by `docs/LEGACY-SITE-ANALYSIS.md`: the legacy `hct.ece.ubc.ca`
WordPress site held real content substance (Vision/Innovation, EDII, Land
Acknowledgment, ~35 sponsors, a multi-audience Opportunities section, and a
37-project archive). Today only the dated **Classic** look surfaces that
content; the three modern looks (Signal/Console/Journal) drop all of it.

## Background — current state (verified)

- **Looks:** one `SiteHome.jsx` renders a sticky selector over four looks.
  `Classic` renders `<Home>` (all the prose sections). The other three share a
  single `Gallery()` component that renders **hero → record → people →
  projects** and nothing else. Default look is `signal`
  (`variants.js:DEFAULT_THEME`).
- **Prose content already exists** in `site_content` (keys: `vision`,
  `innovation`, `contact`, `land_acknowledgment`, `edi`, `sponsors`,
  `opportunities`) and is already fetched by `Gallery` as `content` — it's just
  never rendered there. `Prose.jsx` + `lib/prose.js` render this markdown
  subset today (used by Classic).
- **Archive migration is done:** `backend/data/inputs/projects.yaml` holds 65
  projects (5 `current` + 60 `archived`), every archived entry carrying an
  LLM-written `summary`, `link`, and `image`. This is uncommitted work
  (`git diff`: +742 lines). `sync_content.load_projects_yaml()` turns this YAML
  into `(projects, links, membership)` rows, slugs derived, cleanly separated
  from the Supabase upsert.
- **The frontend already renders archived projects** via
  `splitByKind(projects, "archived")` in `Research.jsx` and the gallery's
  `ProjectGrid`. Nothing shows because the data the frontend reads doesn't
  contain them yet:
  - Production reads the Supabase `research` table (via `getProjects()`).
  - Offline/mock reads `frontend/src/data/snapshot.json` (`research`: only 5
    rows today).
- **No snapshot generator exists** in the repo; `snapshot.json` is an
  un-scripted dump of Supabase.
- **Repo-root `.env` write keys are empty** (`SB_SEC_KEY=`, `OPENROUTER_API_KEY=`),
  so this session cannot push to Supabase or make LLM calls. It does not need
  to: the migration's LLM work is already in the YAML, and the offline demo is
  built from YAML deterministically.

## Confirmed visual bug — Console hero

**Symptom:** in the Console look, the hero title
("Human Communication Technologies Lab") is nearly invisible.

**Root cause (verified via `elementFromPoint` + computed styles):** the global
`styles.css` has a bare element rule
`header { background: rgba(255,255,255,0.85); backdrop-filter: blur(8px);
border-bottom: 1px solid #ddd; }` (the Classic sticky masthead). `.vlab-hero`
is a semantic `<header>`, so that rule leaks in. The gallery reset
(`.vlab header, .vlab footer { display:block; margin:0 }`, `variants.css:90`)
neutralizes *layout* leaks but not *paint* leaks. On the three light looks the
translucent-white slab is white-on-white (invisible); on Console's near-black
`--v-bg: #0a0c10` it paints a light-gray slab under the near-white
(`--v-ink: #d8e0e8`) title.

## Design

### Workstream 1 — fix visual bugs (CSS only)

1. **Console hero:** extend the `.vlab header, .vlab footer` reset in
   `variants.css` to also reset the paint properties the global rule leaks:
   `background: transparent; backdrop-filter: none;
   -webkit-backdrop-filter: none; border-bottom: 0;`. Inert on the light looks,
   fixes Console. Verify by re-inspecting `.vlab-hero` computed `background`
   in Console (expect `rgba(0,0,0,0)`).
2. **Hero balance (Signal/Journal/Console polish):** the hero is heavily
   left-weighted with a large empty right column. Rebalance restrainedly — the
   stat block (`.vlab-stats`) moves into the hero's right column beside the
   title on wide viewports (a two-column hero grid that collapses to one column
   under the existing 760px breakpoint), so the hero reads as intentional, not
   half-drawn. No new components; CSS + light JSX regrouping only.

### Workstream 2 — content-complete modern shell

Add the missing sections to the shared `Gallery()` in `SiteHome.jsx`, themed
with the existing `--v-*` tokens, reusing `Prose.jsx`. New section order:

```
hero (spectrogram + stats)
Vision / Innovation        ← the lab's mission, leads the front door
The record (search/filter) ← unchanged technical centerpiece
People                     ← unchanged
Projects (+ "see all 65")  ← current teased; archive one click away
Opportunities (accordion)  ← the multi-audience "get involved" asks
Sponsors                   ← industry / government / university
EDII + Land Acknowledgment ← the lab's values
Contact                    ← address / email / website
footer
```

Details:
- **Rendering:** a small `<VlabProse sectionKey title>` wrapper reads
  `content[key]` and renders `<Prose text={value.text} />` inside a
  `.vlab-section` with a `.vlab-h2` heading. Reuses the tested
  `lib/prose.js` parser — no new markdown logic.
- **Prose styling under `.vlab`:** add scoped `.vlab .prose` rules to
  `variants.css` (body measure ~65–70ch, token colors, link styling, list
  markers, heading rhythm) so prose inherits each look's palette. Console keeps
  its monospace + `//` section-label treatment; Journal its serif.
- **Opportunities accordion:** the `opportunities` prose is four audience
  sub-sections (Undergraduate / PhD & Master / Research Assistants /
  Post-Docs / Associates & Visiting), each an `##` heading in the markdown.
  Split the parsed blocks on headings into collapsible `<details>`-based panels
  (native, accessible, no dependency, respects reduced-motion). First panel
  open by default. If splitting proves fiddly, fall back to rendering the prose
  as-is (still complete, just not collapsible) — completeness is the hard
  requirement, the accordion is polish.
- **Sponsors:** render the existing slash-separated text list as themed prose
  with its `##` sub-group headings (Industry / Government / University). A
  logo grid is **out of scope** (no logo assets exist yet) and noted as a
  follow-up.
- **Scope guard ("don't go too far"):** monospace/serif section labels,
  hairline rules, restrained spacing. No hero video, no gradients, no marketing
  chrome. All content is live `site_content`; nothing is invented.
- **Classic is untouched** — it already renders all of this via `<Home>`.

### Workstream 3 — surface the 60-project archive

The data is ready (`projects.yaml`). Make it visible on both paths:

1. **Offline demo (this session, no credentials) — a committed snapshot
   builder.** A small script (e.g. `backend/scripts/build_snapshot.py`, run via
   `python -m` from `backend/`) that:
   - loads the existing `frontend/src/data/snapshot.json` (to preserve every
     other table verbatim),
   - calls `sync_content.load_projects_yaml("data/inputs/projects.yaml")` and
     serializes the `ResearchProject` rows into the `research` array using the
     exact columns the frontend reads (`slug, title, tagline, description,
     image, hero_image, kind, sort_order, summary`),
   - rebuilds `project_people` from the returned `links`,
   - writes `snapshot.json` back (stable key order, 2-space indent, trailing
     newline) so the diff is legible.

   This makes all 65 projects render in `VITE_MOCK` mode and fills a real gap
   (the repo had no snapshot generator). It is deterministic and cred-free.
2. **Production (user-run) — `hct-manager sync-content`.** Pushes the same YAML
   to the Supabase `research` table with `SB_SEC_KEY`. Documented as a required
   deploy step the user runs (repo-root `.env` write keys are empty here). No
   frontend change needed — `splitByKind` already renders archived.
3. **Homepage teaser copy:** the existing "See all N projects — including M past
   projects" line becomes truthful once the data is present (65 / 60).

## Non-goals (documented follow-ups)

- Sponsor **logo grid/carousel** — blocked on sourcing logo image assets.
- **Link-health check** on outbound `research.link` (HEAD/GET, flag 4xx/5xx) as
  a `hct-manager qa` extension.
- Reconciling the 270 KB legacy `data/publications.bib` against the CV-derived
  timeline.
- Active-section scrollspy nav.
- Re-running the migration LLM (already done; YAML is the source of truth).

## Testing / verification

- **CSS bug fix:** re-inspect Console `.vlab-hero` computed `background`
  (expect transparent); screenshot all four looks' heroes and confirm the title
  is legible in each.
- **Content-complete shell:** screenshot Signal/Console/Journal end-to-end and
  confirm every section (Vision…Contact) renders and is themed; confirm Classic
  is unchanged.
- **Snapshot builder:** after regenerating, `snapshot.json` `research` has 65
  rows (5 current + 60 archived); the modern homepage shows the current teaser
  and "see all 65"; `ProjectsPage` (`#/projects`) lists current + a "Past
  projects" archived block; a sampled archived project route
  (`#/projects/<slug>`) resolves and renders its summary.
- **Existing unit tests stay green:** `frontend/ $ npm test` (pure helpers) and
  `backend/ $ PYTHONPATH=. pytest` (the builder should have a small test that
  it produces 65 research rows from the YAML fixture without network/LLM).
- **No live calls:** builder uses only local YAML + the existing snapshot; no
  Supabase, no OpenRouter, per repo conventions.

## Files touched (anticipated)

- `frontend/src/components/SiteHome.jsx` — new prose sections in `Gallery()`,
  hero regrouping, a `<VlabProse>` + `<Opportunities>`/accordion helper.
- `frontend/src/variants.css` — header/footer paint reset; hero two-column
  grid; scoped `.vlab .prose` + accordion styles.
- `backend/scripts/build_snapshot.py` (new) + a unit test.
- `frontend/src/data/snapshot.json` — regenerated (research/project_people).
- Docs: note the `sync-content` deploy step; mark LEGACY-SITE-ANALYSIS items
  addressed.
