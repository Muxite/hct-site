# Frontend template & blocks (handoff)

The original HCT page (`frontend/index.html`) has been distilled into two
templates with replaceable regions, for whoever builds the frontend:

- **`frontend/templates/index.template.html`** — the home page skeleton.
- **`frontend/templates/paper.template.html`** — the per-paper detail page.

All data comes from Supabase (read with the publishable key — see
[`FRONTEND-DB.md`](FRONTEND-DB.md) for connection + column details). You don't
touch the backend; you fill placeholders from table rows.

## Style (unchanged from the original page)

- **Stylesheets:** `global.css` (layout, type, colors), `tiles.css` (the
  `.wrapper` grid + `.person-tile` / `.research-tile` cards), `mobile.css`
  (responsive). In the original these load from a `…_files/` folder; the template
  references them as `./assets/`. Keep the three files as-is.
- **Fonts:** Google Fonts via the `css2` link (preconnect to
  `fonts.googleapis.com` / `fonts.gstatic.com`).
- **Layout:** everything is inside a single `<main>`; sections are an `<h2>`
  heading (add `class="section"` for the larger ones: Latest, Contact,
  Publications) followed by content, separated by `<hr>`.
- **Conventions seen in the markup:** muted secondary text uses inline
  `style="color: #888"`; small print uses `style="font-size: 0.83em"`; tile grids
  use `<div class="wrapper">` containing repeated tiles; emails are obfuscated as
  `name [at] domain` in text with a real `mailto:`/Gmail-compose `href`.

## Regions → tables

| Region (in the template)   | Supabase table   | Key columns                                            |
| -------------------------- | ---------------- | ------------------------------------------------------ |
| `{{REGION:TIMELINE}}`      | `timeline`       | `date_label`, `title`, `blurb`, `position` (0 = newest)|
| `{{REGION:PEOPLE}}`        | `people`         | `name`, `role`, `email`, `photo`, `bio`, `sort_order`  |
| `{{REGION:RESEARCH}}`      | `research`       | `title`, `tagline`, `description`, `link`, `image`, `sort_order` |
| `{{REGION:PUBLICATIONS}}`  | `publications`   | `slug`, `title`, `authors`, `year`, `type`, `venue`, `link`, `description` |
| `{{vision}}` `{{innovation}}` `{{contact}}` `{{land_acknowledgment}}` `{{edi}}` `{{sponsors}}` `{{opportunities}}` `{{tagline}}` | `site_content` | row by `key`; text is `value.text` |

## Block shapes (clone one per row)

- **Timeline entry:** `.timeline-entry` → `.timeline-date` + `<strong>` title + blurb.
- **Person:** `.person-tile` → `.photo > img`, `.info` with `<strong>` name,
  `.project` role, `.email > a`. Optional `bio`.
- **Research:** `<a class="research-tile" href=link>` → `.photo > img`, `.info`
  with `<h3>` title + `<h4>` tagline. Optional `description`.
- **Publication:** group rows by `year` (descending). Per year emit
  `<h3 class="year">YEAR</h3>`, then per paper: authors line, `<strong>` title
  (link it to `paper.html?slug=<slug>`), a muted venue/year/`[type]` line, and a
  small `link / bibtex` line. `authors` is a JSON array — join with `; `.

## Per-paper page

Each publication has a page at `paper.html?slug=<slug>` (or pre-render to
`/publications/<slug>.html`). Fetch the one `publications` row by `slug` and fill
`paper.template.html`. The lead paragraph is `description` — the AI-written,
source-grounded short summary produced by `hct-manager describe --fetch`
(condensed from the paper's own page, not invented).

## Notes

- The live `frontend/hct-render/` ES modules already hydrate `index.html` from
  Supabase; these templates are the cleaned-up shape to build from (e.g. in a
  framework) and the contract for the per-paper page, which doesn't exist yet.
- Static markup doubles as the no-JS / DB-unreachable fallback.
