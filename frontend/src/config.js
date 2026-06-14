// Supabase connection + table/key names. The URL and publishable key come from
// Vite env (VITE_SB_*) so they can differ per environment without code changes.
export const SB_URL = import.meta.env.VITE_SB_URL;
export const SB_PUBLISHABLE_KEY = import.meta.env.VITE_SB_PUBLISHABLE_KEY;

export const TABLES = {
  publications: "publications", // slug,title,authors[],year,type,venue,link,bibtex,description
  timeline: "timeline", // full history: slug,title,authors[],year,date_label,blurb,position
  people: "people", // name,role,email,photo,bio,kind,sort_order
  research: "research", // title,tagline,description,link,image,kind,sort_order
  siteContent: "site_content", // key -> value (jsonb)
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
