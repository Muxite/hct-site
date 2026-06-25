/**
 * Pure presentation helpers — no React, no DOM, no network. These hold the
 * grouping/labelling logic ported from the old hct-render renderers so it can be
 * unit-tested under `node --test` (see format.test.js).
 */

export const TYPE_LABELS = {
  article: "Article",
  inproceedings: "Conference",
  preprint: "Preprint",
  book: "Book",
  incollection: "Book chapter",
  thesis: "Thesis",
  techreport: "Tech report",
  misc: "Misc",
};

export function typeLabel(type) {
  return TYPE_LABELS[type] || "Misc";
}

/** Group timeline/publication entries by year, newest year first. */
export function groupByYear(entries) {
  const groups = new Map();
  for (const e of entries || []) {
    const year = e.year ?? e.date_label ?? "—";
    if (!groups.has(year)) groups.set(year, []);
    groups.get(year).push(e);
  }
  return [...groups.entries()].sort((a, b) => Number(b[0]) - Number(a[0]));
}

/**
 * Split a list into [current, archived] by `kind`. The "set-aside" kind
 * (alumni for people, archived for research) goes second; everything else is
 * treated as current.
 */
export function splitByKind(items, setAsideKind) {
  const current = [];
  const setAside = [];
  for (const item of items || []) {
    (item.kind === setAsideKind ? setAside : current).push(item);
  }
  return [current, setAside];
}

/** Format an authors array as "A; B; C". */
export function formatAuthors(authors) {
  return (authors || []).join("; ");
}

/** Turn an email into a lightly-obfuscated display label ("x [at] y"). */
export function emailLabel(email) {
  return String(email || "").replace("@", " [at] ");
}

/**
 * Normalize an asset path from the DB. The lab's data stores photos/images as
 * "./Human Communication Technologies Lab_files/<file>" (the original site's
 * folder, vendored under the app's public/). Strip the leading "./" so the URL
 * is absolute and resolves on any route.
 */
export function assetUrl(path) {
  const p = String(path || "");
  return p.startsWith("./") ? p.slice(1) : p;
}
