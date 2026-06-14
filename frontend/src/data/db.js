/**
 * Data layer — thin wrappers over supabase-js reads. Ported from the old
 * hct-render/data/db.js; the client is built once from Vite env (config.js).
 * Every getter is pure data-in/data-out and accepts an injected client so the
 * pure helpers stay testable.
 */

import { createClient } from "@supabase/supabase-js";
import { SB_URL, SB_PUBLISHABLE_KEY, TABLES } from "../config.js";

let _client = null;

/** Build (and cache) the supabase-js client from the Vite env config. */
export function getClient() {
  if (_client) return _client;
  if (!SB_URL || !SB_PUBLISHABLE_KEY) {
    throw new Error(
      "Missing VITE_SB_URL / VITE_SB_PUBLISHABLE_KEY — copy .env.example to .env",
    );
  }
  _client = createClient(SB_URL, SB_PUBLISHABLE_KEY);
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

export async function getPublication(slug, client = getClient()) {
  const { data, error } = await client
    .from(TABLES.publications)
    .select("slug,title,authors,year,type,venue,link,bibtex,description")
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

export async function getResearch(client = getClient()) {
  const { data, error } = await client
    .from(TABLES.research)
    .select("title,tagline,description,link,image,kind,sort_order")
    .order("sort_order", { ascending: true });
  if (error) throw error;
  return data || [];
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
