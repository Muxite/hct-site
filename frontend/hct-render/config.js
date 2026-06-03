/**
 * hct-render config — the only thing the frontend needs to read the site data.
 *
 * SB_PUBLISHABLE_KEY is the Supabase *publishable* key. It is safe to ship in
 * the browser: every table is RLS-protected and public clients have SELECT only
 * (writes require the backend secret key). Fill these in for your project.
 *
 * The TABLES / CONTENT_KEYS maps document exactly what the database exposes, so
 * a frontend dev only needs this file to know what to query.
 */

export const SB_URL = "https://uashejcjldoedqmgeujc.supabase.co";
export const SB_PUBLISHABLE_KEY = "sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk";

// Tables exposed (read-only) via the Data API.
export const TABLES = {
  publications: "publications", // slug, title, authors[], year, type, venue, link, bibtex, description
  timeline: "timeline", //        title, authors[], year, date_label, blurb, position (0 = newest)
  people: "people", //            name, role, email, photo, bio, kind, sort_order
  research: "research", //        title, tagline, description, link, image, sort_order
  siteContent: "site_content", // key, value (jsonb: { title, text })
};

// Keys available in the site_content key/value table.
export const CONTENT_KEYS = [
  "vision",
  "innovation",
  "contact",
  "land_acknowledgment",
  "edi",
  "sponsors",
  "opportunities",
];
