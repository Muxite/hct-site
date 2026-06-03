import test from "node:test";
import assert from "node:assert/strict";

import { renderTimelineHTML, mountTimeline, escapeHtml } from "./timeline.js";

const ENTRIES = [
  {
    title: "Newest paper",
    authors: ["A Person", "B Person"],
    year: 2023,
    date_label: "2023",
    blurb: "A short blurb.",
    position: 0,
  },
  { title: "Older paper", authors: ["C Person"], year: 2021, date_label: "2021", position: 1 },
];

test("renderTimelineHTML shows date, title, authors and blurb", () => {
  const html = renderTimelineHTML(ENTRIES);
  assert.match(html, /class="timeline-date"[^>]*>2023/);
  assert.match(html, /<strong>Newest paper<\/strong>/);
  assert.match(html, /A Person; B Person/);
  assert.match(html, /A short blurb\./);
  // only the entry with a blurb gets a blurb div (the second has none)
  assert.equal((html.match(/timeline-blurb/g) || []).length, 1);
});

test("renderTimelineHTML escapes untrusted fields", () => {
  const html = renderTimelineHTML([{ title: "<b>x</b>", authors: ["<i>a</i>"], date_label: "2020" }]);
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>x<\/b>/);
});

test("renderTimelineHTML handles empty input", () => {
  assert.match(renderTimelineHTML([]), /Nothing recent/);
});

test("escapeHtml neutralizes markup", () => {
  assert.equal(escapeHtml(`<a>"&'`), "&lt;a&gt;&quot;&amp;&#39;");
});

function fakeEl() {
  return { innerHTML: "", hidden: true };
}
function fakeDoc(map) {
  return { querySelector: (sel) => map[sel] ?? null };
}

test("mountTimeline renders entries and hides fallback", async () => {
  const list = fakeEl();
  const fallback = { hidden: false };
  const doc = fakeDoc({ "#timeline-list": list, "#timeline-static": fallback });
  const out = await mountTimeline({ doc, load: async () => ENTRIES });
  assert.deepEqual(out, ENTRIES);
  assert.match(list.innerHTML, /Newest paper/);
  assert.equal(list.hidden, false);
  assert.equal(fallback.hidden, true);
});

test("mountTimeline leaves fallback on load failure", async () => {
  const list = fakeEl();
  const fallback = { hidden: false };
  const doc = fakeDoc({ "#timeline-list": list, "#timeline-static": fallback });
  const out = await mountTimeline({
    doc,
    load: async () => {
      throw new Error("down");
    },
  });
  assert.equal(out, null);
  assert.equal(fallback.hidden, false);
});
