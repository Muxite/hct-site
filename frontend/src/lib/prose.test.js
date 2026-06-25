import { test } from "node:test";
import assert from "node:assert/strict";

import { parseMarkdown, parseInline } from "./prose.js";

test("parseMarkdown reads headings with level", () => {
  const [b] = parseMarkdown("### Government");
  assert.equal(b.type, "heading");
  assert.equal(b.level, 3);
  assert.equal(b.inline[0].v, "Government");
});

test("parseMarkdown flows single newlines into one paragraph", () => {
  const blocks = parseMarkdown("Altera Inc., US /\n NVIDIA, Inc. /\n Lancaster University");
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, "paragraph");
  // a soft (space) join, not a <br>
  assert.ok(blocks[0].inline.some((n) => n.t === "text" && n.v === " "));
  assert.ok(!blocks[0].inline.some((n) => n.t === "break"));
});

test("parseMarkdown honors hard breaks (two trailing spaces)", () => {
  const [b] = parseMarkdown("2366 Main Mall  \nVancouver, BC");
  assert.ok(b.inline.some((n) => n.t === "break"));
});

test("parseMarkdown builds an ordered list with a nested unordered list", () => {
  const md = [
    "1. First item",
    "2. Send a letter:",
    "   - why you want to work",
    "   - your C.V.",
  ].join("\n");
  const [list] = parseMarkdown(md);
  assert.equal(list.type, "list");
  assert.equal(list.ordered, true);
  assert.equal(list.items.length, 2);
  assert.equal(list.items[1].list.ordered, false);
  assert.equal(list.items[1].list.items.length, 2);
});

test("parseInline parses markdown links and bold", () => {
  const nodes = parseInline("see the [research pages](https://hct.ece.ubc.ca/research) and **bold**");
  const link = nodes.find((n) => n.t === "link");
  assert.equal(link.href, "https://hct.ece.ubc.ca/research");
  assert.equal(link.children[0].v, "research pages");
  assert.ok(nodes.some((n) => n.t === "bold"));
});

test("parseInline auto-links bare URLs and obfuscated emails", () => {
  const url = parseInline("Website: https://hct.ece.ubc.ca").find((n) => n.t === "link");
  assert.equal(url.href, "https://hct.ece.ubc.ca");
  const email = parseInline("Email: ssfels [at] ece.ubc.ca").find((n) => n.t === "link");
  assert.equal(email.href, "mailto:ssfels@ece.ubc.ca");
});
