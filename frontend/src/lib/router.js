/**
 * Minimal hash router — no dependency, works on static hosting (no server
 * rewrite rules needed for deep links). Routes are matched against a small
 * fixed set of patterns; `:param` segments are captured.
 */
import { useEffect, useState } from "react";

function currentPath() {
  const hash = typeof window !== "undefined" ? window.location.hash : "";
  const path = hash.replace(/^#/, "") || "/";
  return path.split("?")[0];
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
