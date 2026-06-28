import { test } from "node:test";
import assert from "node:assert/strict";
import { groupSamples, sampleQuality } from "./samples.js";

const ROWS = [
  { paper_slug: "p2", style: "A", mode: "rag", summary: "p2 A rag", link: "l2", position: 16 },
  { paper_slug: "p1", style: "B", mode: "full", summary: "p1 B full", link: "l1", oa_url: "o1", confidence: 0.9, position: 3 },
  { paper_slug: "p1", style: "A", mode: "rag", summary: "p1 A rag", link: "l1", position: 0 },
  { paper_slug: "p1", style: "A", mode: "full", summary: "p1 A full", link: "l1", position: 1 },
  { paper_slug: "p1", style: "H", mode: "rag", summary: "p1 H rag", link: "l1", position: 4 },
];

test("groupSamples orders papers by lowest position", () => {
  const papers = groupSamples(ROWS);
  assert.deepEqual(papers.map((p) => p.slug), ["p1", "p2"]);
});

test("groupSamples orders styles A..E and maps modes", () => {
  const [p1] = groupSamples(ROWS);
  assert.deepEqual(p1.styles.map((s) => s.style), ["A", "B"]);
  assert.equal(p1.styles[0].modes.rag.summary, "p1 A rag");
  assert.equal(p1.styles[0].modes.full.summary, "p1 A full");
  assert.equal(p1.styles[1].modes.full.summary, "p1 B full");
});

test("groupSamples ignores retired styles", () => {
  const [p1] = groupSamples(ROWS);
  assert.equal(p1.styles.some((s) => s.style === "H"), false);
});

test("groupSamples carries per-paper link fields", () => {
  const [p1] = groupSamples(ROWS);
  assert.equal(p1.link, "l1");
  assert.equal(p1.oa_url, "o1");
  assert.equal(p1.confidence, 0.9);
});

test("groupSamples handles empty input", () => {
  assert.deepEqual(groupSamples(), []);
  assert.deepEqual(groupSamples([]), []);
});

test("sampleQuality returns simple review checks", () => {
  const q = sampleQuality("A grounded paragraph with enough words to pass the short length check cleanly today.");
  assert.equal(q.words, 14);
  assert.deepEqual(q.checks, ["good length", "no em/en dash", "no emoji", "direct opener"]);
});
