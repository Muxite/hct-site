import { test } from "node:test";
import assert from "node:assert/strict";
import {
  yearHistogram,
  buildStats,
  filterPublications,
  pubTypes,
  buildCommandIndex,
  searchCommands,
  isTheme,
  themeById,
  PEOPLE_SECTION_ID,
  shouldReloadGalleryData,
} from "./variants.js";
import { matchRoute } from "./router.js";

test("yearHistogram fills gap years with zero and sorts ascending", () => {
  const h = yearHistogram([{ year: 2000 }, { year: 2000 }, { year: 2003 }]);
  assert.deepEqual(
    h,
    [
      { year: 2000, count: 2 },
      { year: 2001, count: 0 },
      { year: 2002, count: 0 },
      { year: 2003, count: 1 },
    ],
  );
});

test("yearHistogram ignores non-numeric years and empty input", () => {
  assert.deepEqual(yearHistogram([{ year: "n/a" }, {}]), []);
  assert.deepEqual(yearHistogram([]), []);
});

test("buildStats derives span, peak, and counts", () => {
  const s = buildStats({
    pubTotal: 10,
    timeline: [{ year: 1990 }, { year: 1990 }, { year: 1992 }],
    people: [{}, {}],
    projects: [{ kind: "current" }],
  });
  assert.equal(s.publications, 10);
  assert.equal(s.people, 2);
  assert.equal(s.projects, 1);
  assert.equal(s.firstYear, 1990);
  assert.equal(s.lastYear, 1992);
  assert.equal(s.years, 3);
  assert.equal(s.peakYear, 1990);
  assert.equal(s.peakCount, 2);
});

// The hero labels this number "active projects" and teases the archived ones
// separately, so archived rows must not be counted twice over.
test("buildStats counts only non-archived projects, but every person", () => {
  const s = buildStats({
    pubTotal: 0,
    timeline: [],
    people: [{ kind: "current" }, { kind: "alumni" }, { kind: "alumni" }],
    projects: [
      { kind: "current" },
      { kind: "archived" },
      { kind: "archived" },
      { kind: "current" },
      {}, // no kind at all — a live row that simply never set one
    ],
  });
  assert.equal(s.projects, 3);
  assert.equal(s.people, 3); // the roster shows alumni too, so all of them count
});

const PUBS = [
  { title: "Tongue biomechanics", authors: ["S Fels", "I Stavness"], year: 2012, type: "article", venue: "JASA" },
  { title: "Brain to speech", authors: ["A Wei"], year: 2026, type: "inproceedings", venue: "Interspeech" },
  { title: "Old note", authors: ["S Fels"], year: 2012, type: "misc", venue: null },
];

test("filterPublications matches all terms across title/authors/venue", () => {
  assert.equal(filterPublications(PUBS, { query: "tongue" }).length, 1);
  assert.equal(filterPublications(PUBS, { query: "fels 2012" }).length, 2);
  assert.equal(filterPublications(PUBS, { query: "interspeech" }).length, 1);
  assert.equal(filterPublications(PUBS, { query: "nomatch" }).length, 0);
});

test("filterPublications applies year and type filters exactly", () => {
  assert.equal(filterPublications(PUBS, { year: 2012 }).length, 2);
  assert.equal(filterPublications(PUBS, { type: "article" }).length, 1);
  assert.equal(filterPublications(PUBS, { year: 2012, type: "misc" }).length, 1);
});

test("filterPublications with no criteria returns everything", () => {
  assert.equal(filterPublications(PUBS, {}).length, 3);
  assert.equal(filterPublications(PUBS).length, 3);
});

test("pubTypes returns present types in canonical order", () => {
  assert.deepEqual(pubTypes(PUBS), ["article", "inproceedings", "misc"]);
});

// App.jsx's route table, mirrored. Asserting an href's *shape* proved nothing —
// "#/variants#vlab-people" looked right and resolved to no route at all — so
// these tests run the emitted hrefs through the real matcher instead.
const APP_ROUTES = [
  ["/", "home"],
  ["/projects", "projects-index"],
  ["/projects/:slug", "project"],
  ["/papers", "papers-index"],
  ["/papers/:slug", "paper"],
  ["/samples", "samples"],
  ["/variants", "home"],
];

// What the app actually resolves an href to: CommandPalette assigns it to
// window.location.hash, and router.currentPath() strips the "#" and drops the
// query string. Note it does *not* split on a second "#".
const routedPath = (href) => href.replace(/^#/, "").split("?")[0];

test("buildCommandIndex emits hrefs that resolve to real routes", () => {
  const idx = buildCommandIndex({
    publications: [{ title: "P", slug: "p-1", authors: ["A"], year: 2020 }],
    people: [{ name: "Sid", role: "Director" }],
    projects: [{ title: "Brain2Speech", slug: "b2s", tagline: "BCI" }],
  });
  const paper = idx.find((i) => i.kind === "paper");
  const person = idx.find((i) => i.kind === "person");
  const project = idx.find((i) => i.kind === "project");

  assert.equal(paper.href, "#/papers/p-1");
  assert.equal(project.href, "#/projects/b2s");

  for (const item of [paper, project, person]) {
    const match = matchRoute(routedPath(item.href), APP_ROUTES);
    assert.ok(match, `${item.kind} href ${item.href} matches no route`);
  }
  assert.equal(matchRoute(routedPath(paper.href), APP_ROUTES).value, "paper");
  assert.equal(matchRoute(routedPath(project.href), APP_ROUTES).value, "project");
  // People have no page of their own: they land on the gallery homepage, which
  // scrolls to the roster using the ?to= parameter.
  assert.equal(matchRoute(routedPath(person.href), APP_ROUTES).value, "home");
  assert.equal(new URLSearchParams(person.href.split("?")[1]).get("to"), PEOPLE_SECTION_ID);
});

test("buildCommandIndex falls back to a routable href when a row has no slug", () => {
  const idx = buildCommandIndex({
    publications: [{ title: "No slug" }],
    people: [],
    projects: [{ title: "No slug either" }],
  });
  for (const item of idx) {
    assert.ok(matchRoute(routedPath(item.href), APP_ROUTES), `${item.href} matches no route`);
  }
});

test("searchCommands ranks title-prefix matches first and caps results", () => {
  const idx = buildCommandIndex({
    publications: [
      { title: "Speech synthesis", slug: "a", authors: ["X"] },
      { title: "A study of speech", slug: "b", authors: ["Y"] },
    ],
    people: [],
    projects: [],
  });
  const res = searchCommands(idx, "speech", 8);
  assert.equal(res[0].title, "Speech synthesis"); // prefix wins
  assert.equal(searchCommands(idx, "", 1).length, 1); // empty query, limited
});

test("theme guards", () => {
  assert.ok(isTheme("signal"));
  assert.ok(!isTheme("nope"));
  assert.equal(themeById("nope").id, "signal"); // falls back to first
  assert.equal(themeById("console").label, "Console");
});

// --- shouldReloadGalleryData (SiteHome.jsx's Classic -> redesign refetch) ---
// Covers the exact transition logic behind the fix for: land on Signal,
// toggle to Classic, edit something there, toggle back to Signal in the
// same session — Gallery's cached `data` must not go stale. The effect
// itself (useEffect/useState/useRef inside SiteHome) isn't unit-testable
// without a component-render harness (this codebase has none — see earlier
// tasks' reports), but the pure decision it makes each render is.
test("shouldReloadGalleryData bumps on the actual Classic -> redesign transition while editing", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: true, isClassic: false, editMode: true }),
    true,
  );
});

test("shouldReloadGalleryData does nothing for a plain visitor (editMode off)", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: true, isClassic: false, editMode: false }),
    false,
  );
});

test("shouldReloadGalleryData does nothing while still on Classic (not a transition away yet)", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: true, isClassic: true, editMode: true }),
    false,
  );
});

test("shouldReloadGalleryData does nothing going *into* Classic", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: false, isClassic: true, editMode: true }),
    false,
  );
});

test("shouldReloadGalleryData does nothing on first mount (never was on Classic)", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: false, isClassic: false, editMode: true }),
    false,
  );
});

test("shouldReloadGalleryData does nothing while staying on a redesign the whole time", () => {
  assert.equal(
    shouldReloadGalleryData({ wasClassic: false, isClassic: false, editMode: false }),
    false,
  );
});
