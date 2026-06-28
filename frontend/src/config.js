// Supabase connection + table/key names. The URL and publishable key come from
// Vite env (VITE_SB_*) so they can differ per environment without code changes.
export const SB_URL = import.meta.env.VITE_SB_URL;
export const SB_PUBLISHABLE_KEY = import.meta.env.VITE_SB_PUBLISHABLE_KEY;

export const TABLES = {
  publications: "publications",
  timeline: "timeline",
  people: "people",
  research: "research",
  siteContent: "site_content",
  samples: "paper_samples",
};

// site_content keys the page renders. `site_meta` holds the header/nav; the rest
// are free-text prose blocks (all sourced from backend site.yaml).
export const CONTENT_KEYS = [
  "vision",
  "innovation",
  "contact",
  "land_acknowledgment",
  "edi",
  "sponsors",
  "opportunities",
];
