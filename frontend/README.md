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

Those two `VITE_` vars are the only configuration the *browser* build needs, and
they are safe to ship: the publishable key can only `SELECT` under row-level
security. (The backend writes with a separate secret key that never appears
here.)

### Server-side env (Vercel Functions only)

`api/` holds two serverless functions (`trigger-job`, `job-status`) that let a
signed-in admin start the `admin-jobs.yml` GitHub Actions workflow. They run on
the server, read `process.env`, and need four more variables set in **Vercel
Project Settings** — never in `.env.example`, never committed, and never with a
`VITE_` prefix (a `VITE_` prefix is exactly what would inline them into the
public browser bundle):

| Variable | What it's for |
| -------- | ------------- |
| `SB_URL` | Supabase project URL — same value as `VITE_SB_URL`. |
| `SB_SEC_KEY` | Supabase **secret** key. Used only to verify an access token and read `admins`. |
| `GITHUB_PAT` | Token that dispatches the workflow. Use a fine-grained PAT scoped to this repo with "Actions: read and write" only. |
| `GITHUB_REPO` | `owner/repo` (e.g. `Muxite/hct-site`). Optional `GITHUB_REF` picks the branch to run, default `main`. |

Both endpoints are public URLs, so every request is verified server-side first
(`api/_lib/verifyAdmin.js`): the caller's Supabase access token must resolve to
a real user *and* that user's id must be in the `admins` table, or the request
is refused with 403 before anything else happens. `api/_lib/` is a shared-helper
directory, not a route — Vercel skips any path under `api/` containing a `_`
segment.

## What it renders

Everything loads once on mount (`src/App.jsx`) from these Supabase tables:

| Section | Source table | Component |
| ------- | ------------ | --------- |
| Masthead | `site_content` key `site_meta` | `components/Header.jsx` |
| Prose sections | `site_content` (vision, contact, …) | `components/Prose.jsx` |
| People | `people` (`kind`: current/alumni) | `components/People.jsx` |
| Research | `research` (`kind`: current/archived) | `components/Research.jsx` |
| **Publications** (centerpiece) | `publications` | `components/Publications.jsx` — full, year-grouped list |
| AI summary bake-off (`?samples`) | `paper_samples` + `publications` | `components/Samples.jsx` |

> A project-centric restructure (see `../docs/PROJECTS.md`) is in development
> and, once committed, adds real routes (`/`, `/projects/:slug`,
> `/papers/:slug`, `/samples`) via `src/lib/router.js`, replacing the
> `?samples` query-param switch above.

## Layout

```
index.html              Vite entry (loads Google Fonts + /src/main.jsx)
api/                    Vercel serverless functions (server-side, not bundled)
  trigger-job.js        POST: admin-verified GitHub workflow_dispatch
  job-status.js         POST: admin-verified workflow-run status
  _lib/                 shared helpers (not routes): verifyAdmin, github, http
src/
  config.js             Supabase URL/key (from VITE_* env) + table names
  data/db.js            supabase-js client + typed getters
  data/mockClient.js     VITE_MOCK offline mode, backed by data/snapshot.json
  lib/format.js         pure helpers (groupByYear, splitByKind, labels) — TESTED
  lib/format.test.js    node --test unit tests
  lib/prose.js          markdown-subset parser for site_content prose — TESTED
  lib/samples.js         helpers for the paper_samples bake-off view — TESTED
  App.jsx               loads data, lays out the page
  components/*.jsx       Header, Prose, People, Research, Publications, Samples
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
