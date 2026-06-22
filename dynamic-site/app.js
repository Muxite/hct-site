/*
 * Dynamic HCT Lab site.
 *
 * This is the original static site's markup/CSS, but every content section —
 * People, Research, Publications, and the prose blocks (Vision, Innovation,
 * Contact, Land Acknowledgment, EDI, Sponsors, Opportunities) — is rendered
 * live from Supabase (the lab's single source of truth) instead of the
 * baked-in YAML snapshot. That keeps the look identical while making the
 * content complete and current (the static snapshot stopped at 2022; Supabase
 * carries the full history).
 *
 * Reads use the publishable, read-only key under RLS — safe to ship in the
 * browser (the backend is the only writer). See backend CLAUDE.md.
 */
const SB_URL = "https://uashejcjldoedqmgeujc.supabase.co";
const SB_KEY = "sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk";
const PHOTO_FALLBACK = "./Human Communication Technologies Lab_files/person.png";

async function sb(path) {
  const res = await fetch(`${SB_URL}/rest/v1/${path}`, {
    headers: { apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}` },
  });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );

const authorList = (a) => (Array.isArray(a) ? a.join("; ") : String(a ?? ""));
const emailAt = (e) => esc(e).replace("@", " [at] ");
const typeLabel = (t) =>
  t ? t.charAt(0).toUpperCase() + t.slice(1).toLowerCase() : "Misc";

function fail(id, msg) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `<div style="color:#c00">Couldn’t load this section (${esc(msg)}).</div>`;
}

// ---- People -------------------------------------------------------------
function personTile(p) {
  const photo = p.photo || PHOTO_FALLBACK;
  return `<div class="person-tile">
            <div class="photo">
              <img alt="${esc(p.name)}" src="${esc(photo)}" onerror="this.onerror=null;this.src='${PHOTO_FALLBACK}'">
            </div>
            <div class="info">
              <strong>${esc(p.name)}</strong>
              <div class="project" style="white-space: nowrap">${esc(p.role || "")}</div>
              ${p.email ? `<div class="email"><a href="mailto:${esc(p.email)}">${emailAt(p.email)}</a></div>` : ""}
            </div>
          <br></div>`;
}

async function renderPeople() {
  const el = document.getElementById("people");
  if (!el) return;
  const people = await sb(
    "people?select=name,role,email,photo,bio,kind,sort_order&order=sort_order.asc",
  );
  const current = people.filter((p) => p.kind !== "alumni");
  const alumni = people.filter((p) => p.kind === "alumni");
  el.innerHTML = current.map(personTile).join("");
  if (alumni.length) {
    const wrap = document.createElement("div");
    wrap.id = "alumni";
    wrap.className = "wrapper";
    wrap.innerHTML = alumni.map(personTile).join("");
    const heading = document.createElement("h3");
    heading.className = "year";
    heading.textContent = "Alumni";
    el.after(wrap);
    el.after(heading);
  }
}

// ---- Research -----------------------------------------------------------
function researchTile(r) {
  const blurb = r.tagline || r.description || "";
  const inner = `
              <div class="photo">
                ${r.image ? `<img alt="${esc(r.title)}" src="${esc(r.image)}">` : ""}
              </div>
              <div class="info">
                <h3>${esc(r.title)}</h3>
                <h4 class="">${esc(blurb)}</h4>
              </div>`;
  return r.link
    ? `<a class="research-tile" href="${esc(r.link)}">${inner}</a>`
    : `<div class="research-tile">${inner}</div>`;
}

async function renderResearch() {
  const el = document.getElementById("research");
  if (!el) return;
  const projects = await sb(
    "research?select=title,tagline,description,link,image,kind,sort_order&order=sort_order.asc",
  );
  const current = projects.filter((r) => r.kind !== "archived");
  const archived = projects.filter((r) => r.kind === "archived");
  el.innerHTML = [...current, ...archived].map(researchTile).join("");
}

// ---- Publications (full history, grouped by year, newest first) ----------
function pubEntry(p) {
  const venue = p.venue ? `${esc(p.venue)}, ` : "";
  const link = p.link ? `<a href="${esc(p.link)}">link</a>` : "<strike>link</strike>";
  const bib = p.bibtex
    ? `<a href="#" class="bibtex-toggle">bibtex</a>`
    : "<strike>bibtex</strike>";
  return `<div>
            <div>${esc(authorList(p.authors))}</div>
            <div>
              <strong>${esc(p.title)}</strong>
            </div>
            <div style="color: #888">
              ${venue}${esc(p.year)}.
              [${esc(typeLabel(p.type))}]
            </div>
            <div style="font-size: 0.83em">
            ${link} / ${bib}
            </div>${p.bibtex ? `\n            <pre class="bibtex" style="display:none;white-space:pre-wrap">${esc(p.bibtex)}</pre>` : ""}
            <br>
          </div>`;
}

async function renderPublications() {
  const el = document.getElementById("publications-list");
  if (!el) return;
  const pubs = await sb(
    "publications?select=slug,title,authors,year,type,venue,link,bibtex&order=year.desc",
  );
  const byYear = new Map();
  for (const p of pubs) {
    const y = p.year ?? "—";
    if (!byYear.has(y)) byYear.set(y, []);
    byYear.get(y).push(p);
  }
  const years = [...byYear.keys()].sort((a, b) => Number(b) - Number(a));
  el.innerHTML = years
    .map(
      (y) =>
        `<div id="y${esc(y)}"><h3 class="year">${esc(y)}</h3><div>${byYear
          .get(y)
          .map(pubEntry)
          .join("")}</div></div>`,
    )
    .join("");

  // collapsible bibtex (delegated)
  el.addEventListener("click", (e) => {
    const a = e.target.closest(".bibtex-toggle");
    if (!a) return;
    e.preventDefault();
    const entry = a.closest("div[style]")?.parentElement;
    const pre = entry?.querySelector("pre.bibtex");
    if (pre) pre.style.display = pre.style.display === "none" ? "block" : "none";
  });
}

// ---- Prose (Vision / Innovation / Contact / Land Ack / EDI / Sponsors /
//      Opportunities) — all from the site_content key/value store. ----------
const PROSE_KEYS = [
  "vision",
  "innovation",
  "contact",
  "land_acknowledgment",
  "edi",
  "sponsors",
  "opportunities",
];

// Turn URLs and obfuscated "user [at] domain" emails (already HTML-escaped)
// back into links, matching the original page.
function linkify(s) {
  return s
    .replace(
      /(https?:\/\/[^\s<]+[^\s<.,)])/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>',
    )
    .replace(
      /([A-Za-z0-9._%+-]+)\s*[[(]at[\])]\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})/g,
      '<a href="mailto:$1@$2">$1 [at] $2</a>',
    );
}

// A short, punctuation-free single line reads as a sub-heading (the Sponsors /
// Opportunities category labels) — render it like the original <h3><i>.
function isHeading(chunk) {
  return !chunk.includes("\n") && chunk.length <= 55 && !/[.\/,\d]/.test(chunk) && !/[[(]at[\])]/.test(chunk);
}

function proseHTML(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .map((c) => c.trim())
    .filter(Boolean)
    .map((c) =>
      isHeading(c)
        ? `<h3><i>${esc(c)}</i></h3>`
        : `<div>${linkify(esc(c)).replace(/\n/g, "<br>")}</div>`,
    )
    .join("");
}

async function renderProse() {
  const rows = await sb("site_content?select=key,value");
  const map = {};
  for (const r of rows) map[r.key] = r.value;
  for (const key of PROSE_KEYS) {
    const el = document.getElementById("content-" + key);
    if (!el) continue;
    const v = map[key];
    el.innerHTML = v && v.text ? proseHTML(v.text) : "";
  }
}

renderPeople().catch((e) => fail("people", e.message));
renderResearch().catch((e) => fail("research", e.message));
renderPublications().catch((e) => fail("publications-list", e.message));
renderProse().catch((e) => PROSE_KEYS.forEach((k) => fail("content-" + k, e.message)));
