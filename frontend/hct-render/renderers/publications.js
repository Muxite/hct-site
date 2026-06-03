/**
 * hct-render — Publications renderer.
 *
 * Reads the publications from Supabase (via `data/db.js`), renders the entries
 * (grouped by year, newest first) into `#publications-list`, and hides the
 * static fallback (`#publications-static`). Runs client-side in the browser.
 *
 * Pure functions (`renderPublicationsHTML`, `escapeHtml`) are exported for
 * unit testing under Node; the browser bootstrap at the bottom only runs when
 * a real `document` exists.
 */

import { getPublications } from "../data/db.js";

const TYPE_LABELS = {
  article: "Article",
  inproceedings: "Conference",
  preprint: "Preprint",
  book: "Book",
  incollection: "Book chapter",
  thesis: "Thesis",
  techreport: "Tech report",
  misc: "Misc",
};

/** Escape text for safe insertion into HTML (and double-quoted attributes). */
export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** BibTeX is a copyable string, not a URL — reveal it inline when present. */
function renderBibtex(pub) {
  if (!pub.bibtex) return `<strike>bibtex</strike>`;
  return (
    `<details style="display: inline">` +
    `<summary style="display: inline; cursor: pointer">bibtex</summary>` +
    `<pre style="white-space: pre-wrap; margin: 0.25em 0">${escapeHtml(pub.bibtex)}</pre>` +
    `</details>`
  );
}

function renderLinkLine(pub) {
  const link = pub.link
    ? `<a href="${escapeHtml(pub.link)}">link</a>`
    : `<strike>link</strike>`;
  return `<div style="font-size: 0.83em">${link} / ${renderBibtex(pub)}</div>`;
}

function renderEntry(pub) {
  const authors = escapeHtml((pub.authors || []).join("; "));
  const typeLabel = TYPE_LABELS[pub.type] || "Misc";
  const venue = pub.venue ? `${escapeHtml(pub.venue)}, ` : "";
  const desc = pub.description
    ? `<div class="pub-desc" style="font-size: 0.9em; margin-top: 0.25em">${escapeHtml(
        pub.description
      )}</div>`
    : "";
  return `
          <div class="pub-entry">
            <div>${authors}</div>
            <div><strong>${escapeHtml(pub.title)}</strong></div>
            <div style="color: #888">${venue}${pub.year}. [${typeLabel}]</div>
            ${renderLinkLine(pub)}
            ${desc}
            <br>
          </div>`;
}

/** Group publications by year, newest first. */
export function groupByYear(publications) {
  const groups = new Map();
  for (const pub of publications || []) {
    if (!groups.has(pub.year)) groups.set(pub.year, []);
    groups.get(pub.year).push(pub);
  }
  return [...groups.entries()].sort((a, b) => b[0] - a[0]);
}

/**
 * Build the inner HTML for the publications list from a parsed YAML object.
 * Pure: takes data, returns a string. `data.publications` is an array.
 */
export function renderPublicationsHTML(data) {
  const pubs = (data && data.publications) || [];
  if (pubs.length === 0) {
    return `<p class="pub-empty">No publications available.</p>`;
  }
  return groupByYear(pubs)
    .map(([year, entries], i) => {
      const mt = i === 0 ? ` style="margin-top: 0px;"` : "";
      return `<div class="pub-year" id="${year}"><h3 class="year"${mt}>${year}</h3>${entries
        .map(renderEntry)
        .join("")}</div>`;
    })
    .join("");
}

/**
 * Read publications from Supabase, render them into the list element, and hide
 * the fallback. Dependencies are injectable for testing. On any failure the
 * static fallback is left visible and the error is logged.
 */
export async function mountPublications({
  listSelector = "#publications-list",
  fallbackSelector = "#publications-static",
  doc = typeof document !== "undefined" ? document : undefined,
  load = getPublications,
} = {}) {
  if (!doc) throw new Error("mountPublications: no document available");
  const listEl = doc.querySelector(listSelector);
  if (!listEl) throw new Error(`mountPublications: ${listSelector} not found`);

  try {
    const publications = await load();
    listEl.innerHTML = renderPublicationsHTML({ publications });
    listEl.hidden = false;
    const fallback = doc.querySelector(fallbackSelector);
    if (fallback) fallback.hidden = true;
    return publications;
  } catch (err) {
    // Leave the static fallback visible; just surface the reason.
    console.error("hct-render: failed to render publications —", err);
    return null;
  }
}

// Browser bootstrap: auto-run once the DOM is ready. Skipped under Node tests
// (no `document`) and when a host sets `window.__HCT_NO_AUTORENDER`.
if (typeof document !== "undefined" && !globalThis.__HCT_NO_AUTORENDER) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountPublications());
  } else {
    mountPublications();
  }
}
