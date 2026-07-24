# Legacy site analysis — what we must not regress on

Crawled 2026-07-20 with **ujin** (the standalone dev checkout at `../ujin`,
`.venv` synced with `uv sync --extra scrape`, driven directly via
`ujin.scrape.build.build_scrape_service` — no server, no Docker). Raw HTML +
manifests are saved under `docs/regressions/` as the regression baseline.

## What was captured

```
docs/regressions/
  hct-lab-github-io/        # the current landing page (github.io, JS-rendered shell)
    hct-lab-github-io-index.html
    data_profiles.yaml      # data/profiles.yaml — feeds the People tiles client-side
    data_research.yaml      # data/research.yaml — feeds the Research tiles + outbound links
    data_publications.bib   # data/publications.bib — 270 KB, the full legacy pub record
    manifest.json           # per-page fetch metadata (title, links, save path)
    external-links.json     # every link off hct-lab.github.io, deduped w/ source pages
  hct-ece-ubc-ca/            # the old WordPress site the homepage still points to
    hct-ece-ubc-ca-index.html
    hct-ece-ubc-ca-research.html     # the master project index (37 projects, 5 active)
    hct-ece-ubc-ca-brain2speech.html
    hct-ece-ubc-ca-videx.html
    hct-ece-ubc-ca-3d-teleview.html
    hct-ece-ubc-ca-bmodeling.html
    hct-ece-ubc-ca-proj-4.html
    manifest.json
```

Two sites are actually in play, and both are load-bearing:

1. **`hct-lab.github.io`** — the current front door. A hand-rolled static
   shell (`index.html` + `global.css`/`tiles.css`/`mobile.css`) that fetches
   `data/profiles.yaml`, `data/research.yaml`, `data/publications.bib` at
   runtime via jQuery + `js-yaml` + `bibtex-parse-js` and renders tiles/pub
   list client-side. This is the **direct ancestor of our own data model** —
   `profiles.yaml`/`research.yaml` map almost 1:1 to our `people.yaml`/
   `research.yaml`, and `publications.bib` is the same role our CV parse
   fills. `backend/data/inputs/research.yaml`'s 5 "current" entries are a
   verbatim copy of this file's non-archived entries, `link:` field included.
2. **`hct.ece.ubc.ca`** — a 2010s-era WordPress site (theme
   `wp-hybrid-clf`, IE7/8/9 conditional-comment shims still in the markup)
   that every "current" project tile links out to, and whose `/research`
   page is the **real project archive**: 37 projects total, only 5 of which
   are mirrored into our new site as "current" — the other ~32 (Cubee,
   Iamascope, Glove-TalkII, MUSICtable, CRYSTAL, IoT tools, OPAL, …) exist
   only there, several dating back over a decade.

## What's good (keep these)

- **Content substance, not just publications.** Vision/Innovation statement,
  a real EDII section with UBC Faculty of Applied Science links, a land
  acknowledgment, a Sponsors list (industry/government/university, ~35 named
  sponsors), and a detailed multi-audience "Opportunities" section
  (undergrad, grad, postdoc, visiting researcher — each with its own ask).
  None of this exists yet in our `site.yaml` prose — it's real content worth
  porting, not boilerplate to discard.
  **Addressed 2026-07-24** — Vision, Innovation, Opportunities, Sponsors, EDII,
  Land Acknowledgment and Contact render in Signal/Console/Journal (`SiteHome.jsx`).
- **Config-over-code data model.** People/research as flat YAML the PI can
  hand-edit is exactly right for a lab with no one who wants to maintain a
  website — it's the same bet our own `people.yaml`/`research.yaml` make.
- **The project archive itself is valuable history.** 37 projects going back
  years is a real record of lab output, not filler.
- **A single canonical contact/sponsorship story** — one page holds it all,
  nothing scattered across sub-sites.

## What's bad (the regressions to fix, not repeat)

- **Client-side-only rendering with an empty initial DOM.** `#people`,
  `#research`, and `#publications` are empty `<div>`s until 3 sequential
  `$.get()` calls resolve and re-run `Object.entries(...).map(...)` DOM
  surgery. No SEO-visible content, nothing for a non-JS crawler or screen
  reader that doesn't execute scripts, no loading state, no error state if a
  YAML fetch 404s.
- **Split-brain project pages.** The "current" project tiles all send
  visitors *off* the lab's own site to `hct.ece.ubc.ca` — a visually
  unrelated, much older design. Continuity breaks the moment someone clicks
  "Research."
- **Wildly inconsistent tech across project pages.** Sampled 3 of the 5
  "current" project URLs and got 3 different stacks:
  - `videx-…` → real WordPress-rendered HTML (40 KB, server-rendered).
  - `3d-teleview/`, `bmodeling/`, `proj-4/` → same WordPress theme.
  - `brain2speech/` → a **completely different, bundled JS SPA** (`<div
    id="root">` + hashed `app.*.js`/`vendor.*.js`, empty without JS). No
    shared design system, no shared maintenance path — three different
    "someones" clearly built these at three different times.
- **Dead-feeling legacy theme.** `wp-hybrid-clf` with IE7–9 `<!--[if IE
  7]-->` shims still present — this is a WordPress theme from roughly the
  early-2010s Hybrid Core era, not something anyone is going to touch again.
- **The archive is invisible from the new site.** ~32 of 37 historical
  projects (86%) have zero presence in `hct-site` — no route, no card, no
  mention. Anyone landing on the new site sees 5 projects and has no way to
  discover the other three decades of lab output short of knowing to go dig
  up the old WordPress URL.
  **Addressed 2026-07-24** — 65 projects (5 current + 60 archived) in
  `projects.yaml`; offline via `python -m src.snapshot`, production via
  `hct-manager sync-content`.
- **No dedup or link-rot check between the three sources** (github.io yaml,
  WordPress archive, and now Supabase). `research.yaml`'s `link:` fields
  point at pages we don't own and have no health check on — the QA loop
  (`hct-manager qa`) audits Supabase content but nothing watches whether
  these external links still 200.
- **270 KB of BibTeX (`data/publications.bib`) never reconciled against the
  CV.** Worth a one-time diff — if any paper exists in the old `.bib` but not
  in the CV-derived timeline, that's a real gap in "the timeline is the full
  publication history."
- **One maintainer, one inbox.** Every "how do I get involved" path in
  Opportunities funnels to `ssfels@ece.ubc.ca` by hand. That's the whole
  reason this rebuild exists — worth stating plainly in the new site's own
  framing, since it's the actual product thesis.

## Architecture recommendation: absorb, don't just link out

The rebuild already has the right shape for this — `ProjectPage.jsx` renders
`project.summary || project.description` in-house *and* keeps `project.link`
as a secondary "Project site" pointer (`frontend/src/components/
ProjectPage.jsx:60-68`). Today that description is empty for all 5 research
entries, so the secondary link is doing 100% of the work it should be doing
0% of. Concretely:

1. **One-time migration agent**, same shape as `src/cv.py`'s
   deterministic-first/LLM-fallback split: for each of the 37 legacy project
   pages (already scraped into `docs/regressions/hct-ece-ubc-ca/` as a
   fixture set), heuristically pull title/image/tagline from the HTML
   structure the WordPress theme shares across pages, then one LLM call per
   project (same `google/gemini-3-flash-preview`, same per-entry cost
   discipline as CV parsing) to write the lab-voice `description` — mirrors
   `hct-manager describe` exactly, just pointed at scraped project pages
   instead of paper PDFs/links.
2. **Backfill `research.yaml` with `status: archived`** for the ~32 not
   currently mirrored, so `Research.jsx`'s existing archived/current split
   (per `CLAUDE.md`: "archived render under 'Past projects'") actually has
   something to render. This is additive YAML, zero new schema.
3. **Retire outbound links once absorbed.** Once a project has a real
   `description`, the WordPress/SPA `link:` becomes optional provenance, not
   the only content — visitors stop bouncing to a 2013 theme mid-visit.
4. **A link-health check as a `hct-manager qa` extension** — HEAD/GET each
   `research.link`, flag 4xx/5xx, since we now depend on `hct.ece.ubc.ca`
   staying up for anything not yet absorbed.
5. **Reconcile `data/publications.bib` against the CV-derived timeline once**,
   folding any stragglers in as a one-off `cv_parse.py` input rather than a
   permanent second source (keeps "CV wins" intact).

This is the same pitch the whole repo already makes — deterministic
extraction + a cheap per-entry LLM fallback + a human-editable YAML source of
truth — just pointed at the one part of the lab's web presence (37 projects'
worth of institutional memory) that hasn't been migrated yet.

## Frontend litany — bring Classic out of the 2010s

`SiteHome.jsx` ships **`DEFAULT_LOOK = "classic"`** (`frontend/src/components/
SiteHome.jsx:36`) — i.e. every first-time visitor still lands on the
black-on-white, flat-Inter, no-motion look that's a direct port of the
original `global.css`/`tiles.css` (`frontend/src/styles.css:1-6` says as much
in its own header comment). The three modernized redesigns (Signal/Console/
Journal) already exist and work with all the same live data — they're just
opt-in via the selector, not the default. Nothing below is a rewrite; it's
the smallest set of changes that stop the site from reading as 2013.

1. **Make a modern theme the default, not Classic.** One-line change
   (`DEFAULT_LOOK` in `SiteHome.jsx:36`) — the highest-leverage, lowest-effort
   item on this list. `Signal` is already tagged `"Everyday lab site"` in
   `lib/variants.js:13-17` and is the obvious pick. (Side note: `lib/
   variants.js:38` exports `DEFAULT_THEME = "signal"` but nothing imports it
   — `SiteHome.jsx` hardcodes its own default separately. Worth collapsing to
   one source of truth while touching this.)
2. **Give `main` a max content width.** `styles.css:25-32` sets margin/padding
   but no `max-width` — body text runs edge-to-edge on any monitor wider than
   a laptop. Cap it (~880–960px for prose, wider for the tile grids) and
   center it.
3. **Replace the tile-wrapper flex hack with CSS Grid.** `styles.css:89-99`
   uses `flex-flow: row wrap; justify-content: space-between` plus a
   `::after` spacer trick to fake even columns — a classic pre-Grid-era
   workaround. `grid-template-columns: repeat(auto-fill, minmax(260px, 1fr))`
   does this natively with even gaps and no phantom spacer element.
4. **Give tiles a real surface.** Person/research tiles are currently flush
   text + image with no border/elevation. A subtle card (soft shadow or
   1px border, `border-radius`, a hover lift/shadow-deepen transition) reads
   as 2020s with near-zero design risk.
5. **Type scale with actual rhythm.** Right now it's body text at browser
   default and `h2 { font-size: 1.7em; font-weight: 700 }` — one jump, no
   scale. A 4–5 step modular scale (e.g. 1rem/1.125/1.5/2/2.5) with tighter
   `letter-spacing` on headings and a slightly increased body `line-height`
   (1.5–1.6) is a big perceived-modernity win for near-zero layout risk.
6. **Spacing as tokens, not sprinkled px.** `margin: 36px 0`, `24px 24px`,
   etc. are hand-placed throughout `styles.css`. A small `--space-1..6` custom-
   property scale makes future tuning (and the next redesign) mechanical
   instead of archaeological.
7. **Real link styling.** `styles.css:21-23` is just `a { color: inherit }`
   — no visited/hover/focus distinction anywhere outside the themed variants.
   Even a simple underline-on-hover + visible `:focus-visible` ring closes an
   accessibility gap and looks far less "unstyled HTML."
8. **Honor `prefers-color-scheme` in Classic.** Dark mode already exists and
   works in the redesigns (`dark` flag in `lib/variants.js`); Classic has no
   dark variant at all. Doesn't need a full reskin — even inverting the
   existing palette behind a media query stops Classic from being the one
   look that can't go dark.
9. **A little motion, applied sparingly.** Fade/slide-in on scroll for
   section headers, a `transform`+`box-shadow` transition on tile hover
   (pairs with #4) — CSS-only, no new dependency, and it's the single biggest
   "this feels current" signal for the least effort.
10. **Sticky header with a backdrop blur** instead of the header just
    scrolling away with the rest of `main` — cheap (`position: sticky;
    backdrop-filter: blur(...)`) and immediately reads as a modern site
    chrome rather than a 2012 static page.

None of this touches data, routing, or the Supabase contract — it's CSS
(plus one constant flip) against the existing Classic markup, safe to do
incrementally and independently of the migration work above.

## Cross-check against a second design pass

A separate visual-design pass reviewed `hct-lab.github.io` directly (not our
repo) and flagged it as "text-dense, unstyled-default, no hierarchy" —
independent confirmation, since `styles.css:1-6` says outright that Classic
is that same CSS ported near-verbatim. Its critique is Classic's critique.
Reconciled against what already exists in this repo:

| Suggestion | Status here |
|---|---|
| Modern variable sans-serif, real type scale, 65–75ch prose width, 1.6–1.8 line-height | **New** — folds into litany items #2/#5 above |
| People/Research as a card grid with hover states | **New** — litany item #4 |
| Defined accent color + neutral grays, optional dark mode | **Partly done** — Signal/Console/Journal already have a real palette + dark-mode toggle (`lib/variants.js:16`); Classic has neither. Flipping the default (#1) gets this for free; Classic itself still has no palette or dark variant |
| Hero banner (headline, one-line mission, image/gradient) | **New, missing everywhere** — none of the four looks has a real hero; even the redesigns go straight from selector into content. Worth adding once, above the theme switch |
| Sticky nav with active-section highlighting, smooth anchor scroll | **New** — no theme has scrollspy nav today; litany item #10 covers the sticky/blur part but not active-section tracking |
| Filterable/searchable publications instead of a flat chronological dump | **Already built, just not defaulted** — `lib/variants.js:96` (`filterPublications`) + `:109` (`pubTypes`) + live search power exactly this in Signal/Console/Journal. Classic's `Publications.jsx` is the literal flat year-grouped dump being critiqued (confirmed by reading it directly). This is the single strongest argument for #1 (flip the default) over reskinning Classic in place |
| Opportunities as tabs/accordion instead of four stacked headings | **New** — small, contained change to `Prose.jsx`/`Home.jsx` rendering of the `opportunities` block |
| Sponsors as a logo grid/carousel instead of a slash-separated text list | **New, and blocked on assets** — we don't have sponsor logo images at all yet (only the legacy site's text list, ported into `site.yaml` prose); would need logo assets sourced/requested before this is buildable. **Still open 2026-07-24** — blocked on sourcing logo assets. |

Net read: the fastest path to "2020s, not 2010s" is still **flip the default
theme** (litany #1) — it silently resolves the palette, dark-mode, and
search/filter complaints in one line because that work already exists and is
tested. What's left after that flip is genuinely new: a hero section, active-
section nav highlighting, an Opportunities accordion, and a sponsor logo grid
(the last blocked on getting logo assets). All four are additive and don't
require touching Classic or the data layer.
