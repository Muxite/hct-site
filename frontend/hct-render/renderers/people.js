/**
 * hct-render — People renderer. Hydrates the `#people` tile grid from Supabase,
 * preserving the existing `.person-tile` markup. The static tiles remain as a
 * no-JS / fetch-failure fallback. Pure `renderPeopleHTML` is exported for tests.
 */

import { getPeople } from "../data/db.js";

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function mailto(email) {
  const e = escapeHtml(email);
  const label = e.replace("@", " [at] ");
  return `<a href="mailto:${e}">${label}</a>`;
}

function renderTile(p) {
  const photo = p.photo
    ? `<img alt="${escapeHtml(p.name)}" src="${escapeHtml(p.photo)}">`
    : "";
  const role = p.role ? `<div class="project">${escapeHtml(p.role)}</div>` : "";
  const email = p.email ? `<div class="email">${mailto(p.email)}</div>` : "";
  const bio = p.bio ? `<div class="bio" style="font-size: 0.85em">${escapeHtml(p.bio)}</div>` : "";
  return `<div class="person-tile">
            <div class="photo">${photo}</div>
            <div class="info">
              <strong>${escapeHtml(p.name)}</strong>
              ${role}
              ${email}
              ${bio}
            </div>
          <br></div>`;
}

export function renderPeopleHTML(people) {
  const items = people || [];
  if (items.length === 0) return "";
  return items.map(renderTile).join("");
}

export async function mountPeople({
  listSelector = "#people",
  doc = typeof document !== "undefined" ? document : undefined,
  load = getPeople,
} = {}) {
  if (!doc) throw new Error("mountPeople: no document available");
  const listEl = doc.querySelector(listSelector);
  if (!listEl) throw new Error(`mountPeople: ${listSelector} not found`);
  try {
    const people = await load();
    if (people && people.length) listEl.innerHTML = renderPeopleHTML(people);
    return people;
  } catch (err) {
    console.error("hct-render: failed to render people —", err);
    return null;
  }
}

if (typeof document !== "undefined" && !globalThis.__HCT_NO_AUTORENDER) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountPeople());
  } else {
    mountPeople();
  }
}
