import test from "node:test";
import assert from "node:assert/strict";

import {
  escapeHtml,
  groupByYear,
  renderPublicationsHTML,
  mountPublications,
} from "./publications.js";

const SAMPLE = {
  publications: [
    {
      id: "zhu2022-x",
      title: "A unified representation",
      authors: ["Hongzhi Zhu", "Sidney Fels"],
      year: 2022,
      type: "article",
      venue: "IEEE JBHI",
      link: "https://doi.org/10.1109/JBHI.2022.3150242",
      description: "Short writeup.",
    },
    {
      id: "wu2022-y",
      title: "It's Over There",
      authors: ["Fan Wu", "Sidney Fels"],
      year: 2022,
      type: "inproceedings",
    },
    {
      id: "old2019-z",
      title: "Older paper",
      authors: ["A Person"],
      year: 2019,
      type: "preprint",
    },
  ],
};

test("escapeHtml neutralizes markup and quotes", () => {
  assert.equal(
    escapeHtml(`<script>"x" & 'y'`),
    "&lt;script&gt;&quot;x&quot; &amp; &#39;y&#39;"
  );
  assert.equal(escapeHtml(null), "");
});

test("groupByYear sorts years newest-first", () => {
  const groups = groupByYear(SAMPLE.publications);
  assert.deepEqual(groups.map(([y]) => y), [2022, 2019]);
  assert.equal(groups[0][1].length, 2); // two 2022 papers
});

test("renderPublicationsHTML emits year blocks and entry markup", () => {
  const html = renderPublicationsHTML(SAMPLE);
  // year headers, newest first
  assert.ok(html.indexOf('id="2022"') < html.indexOf('id="2019"'));
  assert.match(html, /<h3 class="year" style="margin-top: 0px;">2022<\/h3>/);
  // title + authors + type label + venue
  assert.match(html, /<strong>A unified representation<\/strong>/);
  assert.match(html, /Hongzhi Zhu; Sidney Fels/);
  assert.match(html, /IEEE JBHI, 2022\. \[Article\]/);
  assert.match(html, /\[Conference\]/); // inproceedings -> human label
  // link present -> anchor; absent -> struck
  assert.match(html, /<a href="https:\/\/doi.org\/10.1109\/JBHI.2022.3150242">link<\/a>/);
  assert.match(html, /<strike>link<\/strike>/);
  // optional description rendered only when present
  assert.match(html, /pub-desc/);
});

test("renderPublicationsHTML reveals bibtex when present, strikes it when absent", () => {
  const html = renderPublicationsHTML({
    publications: [
      { id: "a", title: "A", authors: ["X"], year: 2021, type: "misc", bibtex: "@article{a, title={A}}" },
      { id: "b", title: "B", authors: ["Y"], year: 2021, type: "misc" },
    ],
  });
  // present -> clickable <details> with escaped content
  assert.match(html, /<details[^>]*><summary[^>]*>bibtex<\/summary>/);
  assert.match(html, /@article\{a, title=\{A\}\}/);
  // absent -> struck placeholder
  assert.match(html, /<strike>bibtex<\/strike>/);
});

test("renderPublicationsHTML handles empty input", () => {
  assert.match(renderPublicationsHTML({}), /No publications available/);
  assert.match(renderPublicationsHTML({ publications: [] }), /No publications available/);
});

test("renderPublicationsHTML escapes untrusted fields", () => {
  const html = renderPublicationsHTML({
    publications: [
      { id: "x", title: "<b>x</b>", authors: ["<i>a</i>"], year: 2020, type: "misc" },
    ],
  });
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>x<\/b>/);
});

// --- mountPublications with injected fakes -------------------------------

function fakeEl() {
  return { innerHTML: "", hidden: true };
}
function fakeDoc(map) {
  return { querySelector: (sel) => map[sel] ?? null };
}

test("mountPublications renders into list and hides fallback on success", async () => {
  const list = fakeEl();
  const fallback = { hidden: false };
  const doc = fakeDoc({ "#publications-list": list, "#publications-static": fallback });
  const data = await mountPublications({
    doc,
    load: async () => SAMPLE.publications,
  });
  assert.deepEqual(data, SAMPLE.publications);
  assert.match(list.innerHTML, /A unified representation/);
  assert.equal(list.hidden, false);
  assert.equal(fallback.hidden, true);
});

test("mountPublications leaves fallback visible on load failure", async () => {
  const list = fakeEl();
  const fallback = { hidden: false };
  const doc = fakeDoc({ "#publications-list": list, "#publications-static": fallback });
  const res = await mountPublications({
    doc,
    load: async () => {
      throw new Error("supabase down");
    },
  });
  assert.equal(res, null);
  assert.equal(list.innerHTML, ""); // not rendered
  assert.equal(fallback.hidden, false); // still shown
});

test("mountPublications throws when list element is missing", async () => {
  const doc = fakeDoc({});
  await assert.rejects(
    () => mountPublications({ doc, load: async () => [] }),
    /#publications-list not found/
  );
});
