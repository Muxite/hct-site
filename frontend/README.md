# HCT Lab — website (React + Vite)

The public HCT Lab site. It reads all its content from **Supabase** directly in
the browser with the publishable (read-only) key — there is no backend API. The
data is produced by the `hct-manager` pipeline (see the repo root README); this
app only renders it.

## Setup

```bash
cp .env.example .env     # set VITE_SB_URL + VITE_SB_PUBLISHABLE_KEY
npm install
npm run dev              # dev server at http://localhost:5173
npm run build            # production build -> dist/
npm run preview          # serve the built dist/ locally
npm test                 # pure-helper unit tests (node --test)
```

The two env vars are the only configuration. They are safe to ship: the
publishable key can only `SELECT` under row-level security. (The backend writes
with a separate secret key that never appears here.)

## What it renders

Everything loads once on mount (`src/App.jsx`) from these Supabase tables:

| Section | Source table | Component |
| ------- | ------------ | --------- |
| **Timeline** (centerpiece) | `timeline` (full publication history) | `components/Timeline.jsx` — grouped by year, newest first |
| People | `people` (`kind`: current/alumni) | `components/People.jsx` |
| Research | `research` (`kind`: current/archived) | `components/Research.jsx` |
| Prose sections | `site_content` (vision, contact, …) | `components/Section.jsx` |
| Masthead | `site_content` key `site_meta` | `components/Header.jsx` |
| Paper detail (`?paper=<slug>`) | `publications` | `components/PaperDetail.jsx` |

## Layout

```
index.html              Vite entry (loads Google Fonts + /src/main.jsx)
src/
  config.js             Supabase URL/key (from VITE_* env) + table names
  data/db.js            supabase-js client + typed getters (ported from hct-render)
  lib/format.js         pure helpers (groupByYear, splitByKind, labels) — TESTED
  lib/format.test.js    node --test unit tests
  lib/useRoute.js       tiny ?paper=<slug> router (no dependency)
  App.jsx               loads data, lays out the page
  components/*.jsx       Header, Section, Timeline, People, Research, PaperDetail
  styles.css            editorial/archival theme (Fraunces + IBM Plex)
public/assets/          image files referenced as /assets/<file> by the YAMLs
```

## Images

Photos and project images are not committed. Drop them into `public/assets/` and
point `photo:`/`image:` in the backend `people.yaml`/`research.yaml` at
`/assets/<file>`. Until then the site degrades gracefully (monogram tiles for
people; research tiles hide a missing image).

## Deploying

`npm run build` emits a static `dist/`. Host it anywhere that serves static
files (Vercel, Netlify, nginx, GitHub Pages, …). The app is a single page; the
only "route" is the `?paper=<slug>` query param, so no server rewrites are
required.
