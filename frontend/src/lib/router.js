/**
 * Minimal hash router — no dependency, works on static hosting (no server
 * rewrite rules needed for deep links). Routes are matched against a small
 * fixed set of patterns; `:param` segments are captured.
 */
import { useEffect, useState } from "react";

// A defensive guard, not the happy path. data/db.js pins the Supabase client
// to the PKCE flow precisely so an auth callback never lands in this slot:
// PKCE returns its code as a *query* param, so the magic link arrives as
// ".../?code=...#/admin" and the hash holds nothing but our own route.
//
// Under supabase-js's *default* implicit flow it would: the session tokens
// come back in `location.hash` (e.g. `#access_token=...&type=magiclink`) —
// the same slot this router reads paths from. GoTrue can also still put an
// `error=`/`error_description=` on the fragment for a failed callback. Either
// way that isn't one of our routes, so treat it as "/" rather than a bogus
// 404 and let supabase-js (which parses `window.location.href` itself,
// independent of this router) deal with it.
const AUTH_CALLBACK_HASH = /(^|&)(access_token|error|error_description)=/;

/** Pure: derive the router path from a raw `location.hash` value (leading
 * "#" optional, no query string). Exported mainly so the auth-callback guard
 * above is unit-testable without a `window` global. */
export function pathFromHash(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  if (AUTH_CALLBACK_HASH.test(raw)) return "/";
  return raw.split("?")[0] || "/";
}

/** The current hash-routed path, e.g. "/projects/artisynth" (no query string). */
export function currentPath() {
  return pathFromHash(typeof window !== "undefined" ? window.location.hash : "");
}

/** Subscribe to the current hash path; re-renders on navigation. */
export function useHashPath() {
  const [path, setPath] = useState(currentPath());
  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path;
}

/** Navigate to a new hash path (pushes a history entry). */
export function navigate(path) {
  window.location.hash = path;
}

// Counts hash changes since this module loaded (any origin — a plain <a
// href="#/...">, navigate() above, or the browser's own back/forward), not
// just navigate() calls, since most in-app links are bare anchors rather than
// calls through this function. A fresh page load / hard refresh starts at 0.
let hashChangeCount = 0;
if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    hashChangeCount += 1;
  });
}

/** Whether `window.history.back()` would land somewhere inside this app
 * (at least one in-app navigation has happened since page load) rather than
 * off the site entirely or nowhere. Used to make a page's "Back" control
 * return to wherever the visitor actually came from — search results, a
 * project page, the timeline — instead of a single hardcoded destination,
 * while still having something sensible to fall back to for a direct/shared
 * link that skips straight to the page with no prior in-app history. */
export function canGoBack() {
  return hashChangeCount > 0;
}

/**
 * Match `path` against `[pattern, value]` pairs. A pattern segment starting
 * with `:` captures into `params`. Returns `{ value, params }` for the first
 * match, or null.
 */
export function matchRoute(path, routes) {
  const segs = path.split("/").filter(Boolean);
  for (const [pattern, value] of routes) {
    const pSegs = pattern.split("/").filter(Boolean);
    if (pSegs.length !== segs.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < pSegs.length; i++) {
      if (pSegs[i].startsWith(":")) params[pSegs[i].slice(1)] = decodeURIComponent(segs[i]);
      else if (pSegs[i] !== segs[i]) ok = false;
    }
    if (ok) return { value, params };
  }
  return null;
}
