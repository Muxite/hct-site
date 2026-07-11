/**
 * Pure helpers for the /variants design gallery — no React, no DOM, no network.
 * They turn the live Supabase data (publications, timeline, people, projects)
 * into the small derived structures the gallery renders: the year "spectrogram"
 * histogram, the headline stats, the client-side publication filter, and the
 * command-palette index. Kept side-effect-free so they can be unit-tested under
 * `node --test` (see variants.test.js).
 */

/** The four design directions the gallery toggles between. */
export const THEMES = [
  {
    id: "signal",
    label: "Signal",
    blurb: "Modern, warm, light or dark. Everyday lab site.",
    dark: true, // supports the dark-mode toggle
  },
  {
    id: "console",
    label: "Console",
    blurb: "Monospace research console. Query the record.",
    dark: false, // inherently dark; toggle hidden
  },
  {
    id: "journal",
    label: "Journal",
    blurb: "Scholarly serif. The lab as a running publication.",
    dark: false,
  },
  {
    id: "classic",
    label: "Classic",
    blurb: "The current site, unchanged — for reference.",
    dark: false,
  },
];

export const DEFAULT_THEME = "signal";

export function isTheme(id) {
  return THEMES.some((t) => t.id === id);
}

export function themeById(id) {
  return THEMES.find((t) => t.id === id) || THEMES[0];
}

/**
 * Publication cadence as a continuous per-year histogram — the gallery's
 * signature "spectrogram". Every year from the first to the last entry is
 * present (gap years get count 0) so the bars read as a single signal rather
 * than a sparse scatter. Returns `[{ year, count }]` ascending by year.
 */
export function yearHistogram(entries) {
  const counts = new Map();
  for (const e of entries || []) {
    const y = Number(e.year);
    if (!Number.isFinite(y)) continue;
    counts.set(y, (counts.get(y) || 0) + 1);
  }
  if (!counts.size) return [];
  const years = [...counts.keys()];
  const min = Math.min(...years);
  const max = Math.max(...years);
  const out = [];
  for (let y = min; y <= max; y++) out.push({ year: y, count: counts.get(y) || 0 });
  return out;
}

/** Headline counters for the hero. `people`/`projects` count current members. */
export function buildStats({ pubTotal, timeline, people, projects }) {
  const hist = yearHistogram(timeline);
  const first = hist.length ? hist[0].year : null;
  const last = hist.length ? hist[hist.length - 1].year : null;
  const peak = hist.reduce((m, d) => (d.count > m.count ? d : m), { count: 0, year: null });
  return {
    publications: pubTotal ?? (timeline || []).length,
    people: (people || []).length,
    projects: (projects || []).length,
    firstYear: first,
    lastYear: last,
    years: first != null && last != null ? last - first + 1 : 0,
    peakYear: peak.year,
    peakCount: peak.count,
  };
}

const norm = (s) => String(s || "").toLowerCase();

/**
 * Client-side publication filter. `query` matches title / authors / venue
 * (case-insensitive substring); `year` and `type` are exact when set. Pure over
 * the already-loaded rows — the whole 551-row table is fetched once, then
 * filtered here on every keystroke.
 */
export function filterPublications(pubs, { query = "", year = null, type = null } = {}) {
  const q = norm(query).trim();
  const terms = q ? q.split(/\s+/) : [];
  return (pubs || []).filter((p) => {
    if (year != null && Number(p.year) !== Number(year)) return false;
    if (type && p.type !== type) return false;
    if (!terms.length) return true;
    const hay = norm(`${p.title} ${(p.authors || []).join(" ")} ${p.venue || ""} ${p.year}`);
    return terms.every((t) => hay.includes(t));
  });
}

/** Distinct publication types present, in a stable, human-ish order. */
export function pubTypes(pubs) {
  const order = ["article", "inproceedings", "incollection", "book", "thesis", "preprint", "techreport", "misc"];
  const present = new Set((pubs || []).map((p) => p.type).filter(Boolean));
  const known = order.filter((t) => present.has(t));
  const extra = [...present].filter((t) => !order.includes(t));
  return [...known, ...extra];
}

/**
 * Flat, searchable index for the ⌘K palette. Papers and projects link to their
 * own pages; people scroll to the roster on the gallery page (they have no
 * dedicated route). `kind` drives the little tag shown in the palette.
 */
export function buildCommandIndex({ publications, people, projects }) {
  const items = [];
  for (const p of projects || []) {
    items.push({
      kind: "project",
      title: p.title,
      sub: p.tagline || "",
      href: p.slug ? `#/projects/${p.slug}` : "#/",
    });
  }
  for (const m of people || []) {
    items.push({
      kind: "person",
      title: m.name,
      sub: m.role || "",
      href: "#/variants#vlab-people",
    });
  }
  for (const p of publications || []) {
    items.push({
      kind: "paper",
      title: p.title,
      sub: `${(p.authors || [])[0] || ""}${p.year ? " · " + p.year : ""}`,
      href: p.slug ? `#/papers/${p.slug}` : "#/",
    });
  }
  return items;
}

/** Rank command-index items against a query; empty query keeps input order. */
export function searchCommands(index, query, limit = 8) {
  const q = norm(query).trim();
  if (!q) return (index || []).slice(0, limit);
  const terms = q.split(/\s+/);
  const scored = [];
  for (const it of index || []) {
    const hay = norm(`${it.title} ${it.sub}`);
    if (!terms.every((t) => hay.includes(t))) continue;
    // Prefer title prefix matches, then earlier matches.
    const idx = norm(it.title).indexOf(terms[0]);
    scored.push({ it, score: idx === 0 ? 0 : idx < 0 ? 999 : idx + 1 });
  }
  scored.sort((a, b) => a.score - b.score);
  return scored.slice(0, limit).map((s) => s.it);
}
