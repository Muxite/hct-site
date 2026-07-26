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

/**
 * True when `file` looks like an image based on its browser-reported MIME
 * type. Used by components/EditableImage.jsx as the actual enforcement
 * behind its `<input accept="image/*">` — that attribute is a UI hint only
 * and trivially bypassed (e.g. an OS "All files" picker option). This is
 * deliberately just a MIME sniff-check, not a file-size limit or a
 * magic-byte/content sniff — no size policy is specified anywhere in this
 * codebase, so none is invented here.
 */
export function isImageFile(file) {
  return Boolean(file && typeof file.type === "string" && file.type.startsWith("image/"));
}

/**
 * Kebab-case slug for a display name, used to build the admin CMS's photo
 * upload path (`people/<slug>.<ext>` in the site-media bucket — see
 * data/storage.js's uploadToSiteMedia and db/schema.sql's path convention).
 * Mirrors the shape of the backend's `_slugify` (models.py) — lowercase
 * ASCII, non-alphanumerics collapsed to single hyphens, leading/trailing
 * hyphens trimmed — but simpler (no NFKD/curly-quote normalization): a
 * person's name is plain text and photo-path collisions aren't the
 * dedupe-key-critical case a publication/project slug is.
 */
export function slugify(text) {
  return String(text || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * `people/<slug>.<ext>` — the site-media path convention (db/schema.sql) for
 * a person's photo upload. Shared by components/People.jsx (the Classic
 * roster CRUD) and components/SiteHome.jsx (the Signal/Console/Journal
 * "Gallery" roster) so the two independent admin-CRUD surfaces agree on
 * where a given person's photo lives rather than each deriving its own path.
 */
export function photoPath(name, file) {
  const ext = (file.name.split(".").pop() || "jpg").toLowerCase();
  return `people/${slugify(name)}.${ext}`;
}

/**
 * `projects/<slug>.<ext>` — the site-media path convention (db/schema.sql)
 * for a project's hero image upload. `slug` is `research.slug`, already a
 * stable dedupe key (see backend's `project_slug_for`), so — unlike
 * `photoPath` — this doesn't need to slugify anything itself.
 */
export function projectImagePath(slug, file) {
  const ext = (file.name.split(".").pop() || "jpg").toLowerCase();
  return `projects/${slug}.${ext}`;
}

/**
 * `papers/<slug>.<ext>` — the site-media path convention (db/schema.sql) for
 * a publication's representative image upload. `slug` is `publications.slug`,
 * already a stable dedupe key, so — like `projectImagePath` — this doesn't
 * need to slugify anything itself.
 */
export function paperImagePath(slug, file) {
  const ext = (file.name.split(".").pop() || "jpg").toLowerCase();
  return `papers/${slug}.${ext}`;
}
