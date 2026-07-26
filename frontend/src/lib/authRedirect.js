/**
 * Where a magic-link sign-in should land.
 *
 * A one-line string build, pulled out here rather than left inline in
 * context/AdminContext.jsx because it is load-bearing and silently breakable:
 * the URL's *shape* has to survive supabase-js's auth-callback parser, and
 * getting it wrong doesn't throw — it just means no session is ever
 * established and the only door into the admin CMS stops opening. Sibling
 * authRedirect.test.js pins that shape (and the reason for it) so a future
 * edit can't quietly regress it.
 */

/**
 * The `emailRedirectTo` for `signInWithOtp` — the site's own `#/admin` route.
 *
 * Built from origin + pathname (not a bare origin) so it keeps working if the
 * app is ever served from a sub-path. Takes a `{ origin, pathname }` rather
 * than reading `window` so it's testable without a DOM; callers pass
 * `window.location`.
 *
 * Safe *only* under the PKCE auth flow, which data/db.js pins the client to.
 * PKCE returns its code as a query param, so the callback is
 * `<origin><path>?code=...#/admin` — supabase-js reads `code` from
 * `url.searchParams` and this app's hash router reads `/admin` from the hash,
 * with no overlap. Under supabase-js's *default* implicit flow the session
 * tokens come back on the fragment instead and collide with the `#/admin`
 * here; see the note in data/db.js and the test alongside this file.
 */
export function adminRedirectUrl({ origin, pathname } = {}) {
  return `${origin || ""}${pathname || "/"}#/admin`;
}
