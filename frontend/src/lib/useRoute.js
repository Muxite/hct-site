import { useEffect, useState, useCallback } from "react";

/**
 * Tiny client-side router (no dependency). The only "route" is the optional
 * `?paper=<slug>` query param that switches the page to a paper detail view.
 * `navigate` pushes history; back/forward work via popstate.
 */
export function useRoute() {
  const read = () => new URLSearchParams(window.location.search).get("paper");
  const [paper, setPaper] = useState(read);

  useEffect(() => {
    const onPop = () => setPaper(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((slug) => {
    const url = slug ? `?paper=${encodeURIComponent(slug)}` : window.location.pathname;
    window.history.pushState({}, "", url);
    setPaper(slug || null);
    window.scrollTo(0, 0);
  }, []);

  return { paper, navigate };
}
