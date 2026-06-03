/**
 * hct-render — Research renderer. Hydrates the `#research` tile grid from
 * Supabase, preserving the existing `.research-tile` anchor markup. The static
 * tiles remain as a fallback. Pure `renderResearchHTML` is exported for tests.
 */

import { getResearch } from "../data/db.js";

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderTile(r) {
  const href = r.link ? ` href="${escapeHtml(r.link)}"` : "";
  const photo = r.image
    ? `<img alt="${escapeHtml(r.title)}" src="${escapeHtml(r.image)}">`
    : "";
  // Prefer the AI description; fall back to the short tagline.
  const blurb = escapeHtml(r.description || r.tagline || "");
  return `<a class="research-tile"${href}>
              <div class="photo">${photo}</div>
              <div class="info">
                <h3>${escapeHtml(r.title)}</h3>
                <h4>${blurb}</h4>
              </div>
          </a>`;
}

export function renderResearchHTML(projects) {
  const items = projects || [];
  if (items.length === 0) return "";
  return items.map(renderTile).join("");
}

export async function mountResearch({
  listSelector = "#research",
  doc = typeof document !== "undefined" ? document : undefined,
  load = getResearch,
} = {}) {
  if (!doc) throw new Error("mountResearch: no document available");
  const listEl = doc.querySelector(listSelector);
  if (!listEl) throw new Error(`mountResearch: ${listSelector} not found`);
  try {
    const projects = await load();
    if (projects && projects.length) listEl.innerHTML = renderResearchHTML(projects);
    return projects;
  } catch (err) {
    console.error("hct-render: failed to render research —", err);
    return null;
  }
}

if (typeof document !== "undefined" && !globalThis.__HCT_NO_AUTORENDER) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountResearch());
  } else {
    mountResearch();
  }
}
