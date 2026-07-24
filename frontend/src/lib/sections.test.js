import { test } from "node:test";
import assert from "node:assert/strict";

import { splitSections } from "./sections.js";

test("splitSections returns leading blocks as intro", () => {
  const { intro, sections } = splitSections("Grateful to our sponsors.\n\n### Government\n\nNSERC / CIHR");
  assert.equal(intro.length, 1);
  assert.equal(intro[0].type, "paragraph");
  assert.equal(sections.length, 1);
  assert.equal(sections[0].title, "Government");
});

test("splitSections groups blocks under their heading", () => {
  const text = [
    "### Undergraduate Students",
    "",
    "Check the capstone page.",
    "",
    "### PhD and Master Students",
    "",
    "Always looking for excellent students.",
    "",
    "- a required letter",
    "- a transcript",
  ].join("\n");
  const { intro, sections } = splitSections(text);
  assert.equal(intro.length, 0);
  assert.deepEqual(sections.map((s) => s.title), [
    "Undergraduate Students",
    "PhD and Master Students",
  ]);
  assert.equal(sections[0].blocks.length, 1);
  assert.equal(sections[1].blocks.length, 2);
  assert.equal(sections[1].blocks[1].type, "list");
});

test("splitSections keeps a deeper heading inside its parent section", () => {
  const { sections } = splitSections("## Group\n\nlead\n\n### Sub\n\ndetail\n\n## Other\n\ntail");
  assert.deepEqual(sections.map((s) => s.title), ["Group", "Other"]);
  // the deeper "### Sub" heading stays as a block inside "Group"
  assert.equal(sections[0].blocks.length, 3);
  assert.equal(sections[0].blocks[1].type, "heading");
});

test("splitSections flattens bold and links in a heading title", () => {
  const { sections } = splitSections("### **Post-Docs** and [Visitors](https://example.com)\n\nx");
  assert.equal(sections[0].title, "Post-Docs and Visitors");
});

test("splitSections returns each section's raw markdown without its heading", () => {
  const text = "### Government\n\nNSERC / CIHR\n\n### University\n\nUBC";
  const { sections } = splitSections(text);
  assert.equal(sections[0].text, "NSERC / CIHR");
  assert.equal(sections[1].text, "UBC");
  // the heading line itself is never part of the body
  assert.ok(!sections[0].text.includes("###"));
});

test("splitSections returns the lead paragraph as introText", () => {
  const { introText } = splitSections("Grateful to our sponsors.\n\n### Government\n\nNSERC");
  assert.equal(introText, "Grateful to our sponsors.");
  // a "#" inside a URL must not be mistaken for a heading
  const { introText: t2 } = splitSections("See https://x.test/a#frag here.\n\n### G\n\nn");
  assert.equal(t2, "See https://x.test/a#frag here.");
});

test("splitSections tolerates empty and headingless text", () => {
  assert.deepEqual(splitSections(""), { intro: [], introText: "", sections: [] });
  const flat = splitSections("Just a paragraph.");
  assert.equal(flat.sections.length, 0);
  assert.equal(flat.intro.length, 1);
  assert.equal(flat.introText, "Just a paragraph.");
});
