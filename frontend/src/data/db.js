/**
 * Data layer — thin wrappers over supabase-js reads. Ported from the old
 * hct-render/data/db.js; the client is built once from Vite env (config.js).
 * Every getter is pure data-in/data-out and accepts an injected client so the
 * pure helpers stay testable.
 */

import { createClient } from "@supabase/supabase-js";
import { SB_URL, SB_PUBLISHABLE_KEY, TABLES } from "../config.js";
import { createMockClient } from "./mockClient.js";

let _client = null;

/**
 * True under an offline `VITE_MOCK` build. Pulled out as a pure function (env
 * injectable) so it's unit-testable, and so `context/AdminContext.jsx` can
 * reuse the exact same check `getClient()` uses below rather than re-deriving
 * its own — the mock client has no `.auth`, so every `supabase.auth.*` call
 * must be skipped whenever this is true.
 */
export function isMockMode(env = import.meta.env) {
  return Boolean(env.VITE_MOCK);
}

/** Build (and cache) the supabase-js client from the Vite env config. */
export function getClient() {
  if (_client) return _client;
  // Offline mode: a VITE_MOCK build serves a snapshot of the live Supabase data
  // with no network or keys (the snapshot itself is a lazy chunk — see
  // mockClient.js — so a normal build's bundle never includes it).
  if (isMockMode()) {
    _client = createMockClient();
    return _client;
  }
  if (!SB_URL || !SB_PUBLISHABLE_KEY) {
    throw new Error(
      "Missing VITE_SB_URL / VITE_SB_PUBLISHABLE_KEY — copy .env.example to .env",
    );
  }
  _client = createClient(SB_URL, SB_PUBLISHABLE_KEY);
  return _client;
}

const PUB_COLS = "slug,title,authors,year,type,venue,link,bibtex,description";
const PUB_COLS_FULL = `${PUB_COLS},project_slug,summary_plain,summary_abstract,summary_par,image`;

/**
 * One page of the full publication list, newest year first. Callers drive
 * "load more" with `offset` — the whole 500+ row table is never fetched at
 * once. Returns `{ rows, total }` so the caller knows when it's exhausted.
 */
export async function getPublicationsPage(
  { offset = 0, limit = 30 } = {},
  client = getClient(),
) {
  const { data, error, count } = await client
    .from(TABLES.publications)
    .select(PUB_COLS, { count: "exact" })
    .order("year", { ascending: false })
    .order("slug", { ascending: true })
    .range(offset, offset + limit - 1);
  if (error) throw error;
  return { rows: data || [], total: count ?? 0 };
}

/** Metadata for a known set of publication slugs (e.g. the samples bake-off). */
export async function getPublicationsBySlugs(slugs, client = getClient()) {
  if (!slugs || !slugs.length) return [];
  const { data, error } = await client
    .from(TABLES.publications)
    .select(PUB_COLS)
    .in("slug", slugs);
  if (error) throw error;
  return data || [];
}

export async function getPublication(slug, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.publications)
    .select(PUB_COLS_FULL)
    .eq("slug", slug)
    .maybeSingle();
  if (error) throw error;
  return data || null;
}

export async function getTimeline(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.timeline)
    .select("slug,title,authors,year,date_label,blurb,position")
    .order("position", { ascending: true });
  if (error) throw error;
  return data || [];
}

export async function getPeople(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.people)
    .select("name,role,email,photo,bio,kind,sort_order")
    .order("sort_order", { ascending: true });
  if (error) throw error;
  return data || [];
}

// Lighter columns for the home page's project grid; `summary` (the long
// project-page body) is only fetched per-project on the project page itself.
const PROJECT_GRID_COLS = "slug,title,tagline,description,image,hero_image,kind,sort_order,link";

export async function getProjects(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.research)
    .select(PROJECT_GRID_COLS)
    .order("sort_order", { ascending: true });
  if (error) throw error;
  return data || [];
}

export async function getProject(slug, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.research)
    .select(`${PROJECT_GRID_COLS},summary`)
    .eq("slug", slug)
    .maybeSingle();
  if (error) throw error;
  return data || null;
}

/** Lab members linked to a project (join rows only — see People below for bios). */
export async function getProjectPeople(slug, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.projectPeople)
    .select("person_name,role_on_project,sort_order")
    .eq("project_slug", slug)
    .order("sort_order", { ascending: true });
  if (error) throw error;
  return data || [];
}

/** People rows for a known set of names (used to flesh out project_people links). */
export async function getPeopleByNames(names, client = getClient()) {
  if (!names || !names.length) return [];
  const { data, error } = await client
    .from(TABLES.people)
    .select("name,role,email,photo,bio,kind")
    .in("name", names);
  if (error) throw error;
  return data || [];
}

/** Member papers for a project, small footprint (list card fields only). */
export async function getProjectPapers(slug, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.publications)
    .select("slug,title,authors,year,venue,link,image,summary_plain")
    .eq("project_slug", slug)
    .order("year", { ascending: false });
  if (error) throw error;
  return data || [];
}

/**
 * Report whether a PostgREST error means the optional samples table is absent.
 *
 * :param error: Supabase query error.
 * :returns: true when the error is the schema-cache miss for paper_samples.
 */
export function isMissingSamplesTable(error) {
  const message = String(error?.message || "");
  return (
    error?.code === "PGRST205" ||
    (message.includes("paper_samples") && message.includes("schema cache"))
  );
}

export async function getPaperSamples(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.samples)
    .select(
      "paper_slug,style,mode,model,summary,link,oa_url,confidence,prompt_tokens,completion_tokens,latency_s,position",
    )
    .order("position", { ascending: true });
  if (error && isMissingSamplesTable(error)) return [];
  if (error) throw error;
  return data || [];
}

/**
 * Whether `userId` belongs to the `admins` allowlist (see context/AdminContext.jsx).
 * The table's RLS policy only lets a user read their *own* row
 * (`user_id = auth.uid()`), so a signed-in non-admin's query isn't an error —
 * it just comes back with no row, which resolves to `false` here rather than
 * throwing.
 */
export async function getAdminStatus(userId, client = getClient()) {
  if (!userId) return false;
  const { data, error } = await client
    .from(TABLES.admins)
    .select("user_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw error;
  return Boolean(data);
}

/** All site_content rows as a { key: value } map (one round trip). */
export async function getSiteContent(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.siteContent)
    .select("key,value");
  if (error) throw error;
  const map = {};
  for (const row of data || []) map[row.key] = row.value;
  return map;
}
