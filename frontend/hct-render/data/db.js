/**
 * hct-render data layer — thin wrappers over supabase-js reads.
 *
 * The Supabase client is created lazily from `config.js` using the global
 * `window.supabase` UMD build (loaded via CDN in index.html). Every getter is
 * pure data-in/data-out and accepts an injected client for unit testing under
 * Node (no network, no globals).
 */

import { SB_URL, SB_PUBLISHABLE_KEY, TABLES } from "../config.js";

let _client = null;

/** Lazily build (and cache) the supabase-js client from the global UMD build. */
export function getClient() {
  if (_client) return _client;
  const lib = typeof window !== "undefined" ? window.supabase : undefined;
  if (!lib || !lib.createClient) {
    throw new Error("supabase-js (window.supabase) is unavailable");
  }
  _client = lib.createClient(SB_URL, SB_PUBLISHABLE_KEY);
  return _client;
}

export async function getPublications(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.publications)
    .select("slug,title,authors,year,type,venue,link,bibtex,description")
    .order("year", { ascending: false });
  if (error) throw error;
  return data || [];
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

export async function getResearch(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.research)
    .select("title,tagline,description,link,image,sort_order")
    .order("sort_order", { ascending: true });
  if (error) throw error;
  return data || [];
}

export async function getContent(key, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.siteContent)
    .select("key,value")
    .eq("key", key)
    .maybeSingle();
  if (error) throw error;
  return data ? data.value : null;
}
