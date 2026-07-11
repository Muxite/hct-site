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
} from "./variants.js";

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
    projects: [{}],
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

test("buildCommandIndex links papers/projects to pages, people to roster", () => {
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
  assert.match(person.href, /vlab-people/);
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
