import test from "node:test";
import assert from "node:assert/strict";

import { renderPeopleHTML, mountPeople } from "./people.js";
import { renderResearchHTML, mountResearch } from "./research.js";

function fakeEl() {
  return { innerHTML: "", hidden: true };
}
function fakeDoc(map) {
  return { querySelector: (sel) => map[sel] ?? null };
}

test("renderPeopleHTML builds person tiles with mailto and escaping", () => {
  const html = renderPeopleHTML([
    { name: "Prof. Sid Fels", role: "Director", email: "ssfels@ece.ubc.ca", photo: "sid.png" },
    { name: "<x>", role: null, email: null, photo: null },
  ]);
  assert.match(html, /class="person-tile"/);
  assert.match(html, /<strong>Prof\. Sid Fels<\/strong>/);
  assert.match(html, /href="mailto:ssfels@ece\.ubc\.ca"/);
  assert.match(html, /ssfels \[at\] ece\.ubc\.ca/); // display form
  assert.match(html, /&lt;x&gt;/); // escaped name
});

test("renderResearchHTML prefers description over tagline", () => {
  const html = renderResearchHTML([
    { title: "Brain2Speech", tagline: "short", description: "long desc", link: "https://x/", image: "b.png" },
    { title: "MR", tagline: "tag only" },
  ]);
  assert.match(html, /class="research-tile" href="https:\/\/x\/"/);
  assert.match(html, /<h3>Brain2Speech<\/h3>/);
  assert.match(html, /<h4>long desc<\/h4>/); // description wins
  assert.match(html, /<h4>tag only<\/h4>/); // falls back to tagline
});

test("mountPeople hydrates #people from the loader", async () => {
  const el = fakeEl();
  const doc = fakeDoc({ "#people": el });
  await mountPeople({ doc, load: async () => [{ name: "X" }] });
  assert.match(el.innerHTML, /<strong>X<\/strong>/);
});

test("mountResearch leaves DOM untouched on empty load", async () => {
  const el = { innerHTML: "ORIGINAL" };
  const doc = fakeDoc({ "#research": el });
  await mountResearch({ doc, load: async () => [] });
  assert.equal(el.innerHTML, "ORIGINAL"); // static fallback preserved
});

test("mountPeople leaves DOM untouched on load failure", async () => {
  const el = { innerHTML: "ORIGINAL" };
  const doc = fakeDoc({ "#people": el });
  const out = await mountPeople({
    doc,
    load: async () => {
      throw new Error("down");
    },
  });
  assert.equal(out, null);
  assert.equal(el.innerHTML, "ORIGINAL");
});
