/**
 * Dev-only "fake admin" override for screenshot/QA passes (see
 * `.env.example` for the flag itself and `context/AdminContext.jsx` for
 * where this gets consumed).
 *
 * The lab's single admin account is seeded by hand in Supabase and no
 * account exists yet in some environments (e.g. a fresh screenshot-review
 * checkout), so there's no real session to sign in with. `VITE_ADMIN_PREVIEW`
 * lets a local dev server force `isAdmin`/`editMode` true — skipping the real
 * `getSession()`/`admins`-table lookup entirely — so a screenshot agent can
 * capture the admin editing UI (the `isAdmin && editMode`-gated pencils in
 * Home.jsx/People.jsx/ProjectPage.jsx/PaperPage.jsx/SiteHome.jsx) without one.
 *
 * Gated on *both* the env var and `import.meta.env.DEV` (Vite's own built-in
 * flag, documented for exactly this "tree-shaken/inert in production builds"
 * use — see https://vite.dev/guide/env-and-mode#env-variables): a plain
 * `vite build` always resolves with `NODE_ENV=production`, which makes `DEV`
 * false regardless of `--mode` or of stray env vars, so even if
 * `VITE_ADMIN_PREVIEW` were ever accidentally set in a real Vercel production
 * environment, this stays inert there. `import.meta.env.*` values are
 * build-time constants baked in by esbuild/Rollup, not something a running
 * test can flip — this pure function is the extracted, actually-testable
 * piece of that decision; see adminPreview.test.js.
 */
export function shouldForceAdminPreview({ envFlag, isDev } = {}) {
  return Boolean(envFlag) && Boolean(isDev);
}
