/**
 * hct-render — "Latest" timeline renderer.
 *
 * Reads the timeline (5 most recent publications, newest first) from Supabase
 * and renders compact dated entries into `#timeline-list`. Pure
 * `renderTimelineHTML` is exported for Node tests; the bootstrap runs only in a
 * browser.
 */

import { getTimeline } from "../data/db.js";

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderEntry(item) {
  const authors = escapeHtml((item.authors || []).join("; "));
  const dateLabel = escapeHtml(item.date_label ?? item.year ?? "");
  const blurb = item.blurb
    ? `<div class="timeline-blurb" style="font-size: 0.9em; margin-top: 0.25em">${escapeHtml(
        item.blurb
      )}</div>`
    : "";
  return `
          <div class="timeline-entry">
            <div class="timeline-date" style="color: #888">${dateLabel}</div>
            <div><strong>${escapeHtml(item.title)}</strong></div>
            <div style="font-size: 0.85em">${authors}</div>
            ${blurb}
            <br>
          </div>`;
}

/** Build the inner HTML for the timeline list from an array of entries. */
export function renderTimelineHTML(entries) {
  const items = entries || [];
  if (items.length === 0) {
    return `<p class="timeline-empty">Nothing recent to show.</p>`;
  }
  return items.map(renderEntry).join("");
}

export async function mountTimeline({
  listSelector = "#timeline-list",
  fallbackSelector = "#timeline-static",
  doc = typeof document !== "undefined" ? document : undefined,
  load = getTimeline,
} = {}) {
  if (!doc) throw new Error("mountTimeline: no document available");
  const listEl = doc.querySelector(listSelector);
  if (!listEl) throw new Error(`mountTimeline: ${listSelector} not found`);

  try {
    const entries = await load();
    listEl.innerHTML = renderTimelineHTML(entries);
    listEl.hidden = false;
    const fallback = doc.querySelector(fallbackSelector);
    if (fallback) fallback.hidden = true;
    return entries;
  } catch (err) {
    console.error("hct-render: failed to render timeline —", err);
    return null;
  }
}

if (typeof document !== "undefined" && !globalThis.__HCT_NO_AUTORENDER) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountTimeline());
  } else {
    mountTimeline();
  }
}
