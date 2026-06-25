import { test } from "node:test";
import assert from "node:assert/strict";

import { parseProse } from "./prose.js";

test("parseProse splits blocks on blank lines", () => {
  const blocks = parseProse("First para.\n\nSecond para.");
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "para");
  assert.equal(blocks[1].type, "para");
});

test("parseProse treats a short punctuation-free line as a heading", () => {
  const [block] = parseProse("Platinum Sponsors");
  assert.equal(block.type, "heading");
  assert.equal(block.text, "Platinum Sponsors");
});

test("parseProse linkifies URLs", () => {
  const [block] = parseProse("See https://hct.ece.ubc.ca for more.");
  const link = block.lines[0].find((n) => n.t === "link");
  assert.equal(link.href, "https://hct.ece.ubc.ca");
  assert.equal(link.label, "https://hct.ece.ubc.ca");
});

test("parseProse turns obfuscated emails into mailto links", () => {
  const [block] = parseProse("Reach us at sid [at] ece.ubc.ca today.");
  const link = block.lines[0].find((n) => n.t === "link");
  assert.equal(link.href, "mailto:sid@ece.ubc.ca");
  assert.equal(link.label, "sid [at] ece.ubc.ca");
});

test("parseProse keeps multiple lines within a block", () => {
  const [block] = parseProse("Line one\nLine two");
  assert.equal(block.type, "para");
  assert.equal(block.lines.length, 2);
});
