import test from "node:test";
import assert from "node:assert/strict";

import {
  getPublications,
  getTimeline,
  getPeople,
  getResearch,
  getContent,
} from "./db.js";

/** Minimal chainable fake of the supabase-js query builder. */
function fakeClient(responses) {
  const calls = [];
  return {
    calls,
    from(table) {
      calls.push(table);
      const resp = responses[table] ?? { data: [], error: null };
      const builder = {
        select() {
          return builder;
        },
        order() {
          return Promise.resolve(resp);
        },
        eq() {
          return builder;
        },
        maybeSingle() {
          return Promise.resolve(resp);
        },
      };
      return builder;
    },
  };
}

test("getPublications returns rows from the publications table", async () => {
  const rows = [{ slug: "a", title: "A", year: 2022 }];
  const client = fakeClient({ publications: { data: rows, error: null } });
  assert.deepEqual(await getPublications(client), rows);
  assert.deepEqual(client.calls, ["publications"]);
});

test("getTimeline returns rows from the timeline table", async () => {
  const rows = [{ title: "T", position: 0 }];
  const client = fakeClient({ timeline: { data: rows, error: null } });
  assert.deepEqual(await getTimeline(client), rows);
});

test("getPeople / getResearch read their tables", async () => {
  const client = fakeClient({
    people: { data: [{ name: "X" }], error: null },
    research: { data: [{ title: "R" }], error: null },
  });
  assert.deepEqual(await getPeople(client), [{ name: "X" }]);
  assert.deepEqual(await getResearch(client), [{ title: "R" }]);
});

test("getContent returns the value jsonb for a key", async () => {
  const client = fakeClient({
    site_content: { data: { key: "vision", value: { text: "hi" } }, error: null },
  });
  assert.deepEqual(await getContent("vision", client), { text: "hi" });
});

test("getContent returns null when key is absent", async () => {
  const client = fakeClient({ site_content: { data: null, error: null } });
  assert.equal(await getContent("missing", client), null);
});

test("getters throw on a supabase error", async () => {
  const client = fakeClient({ publications: { data: null, error: new Error("rls") } });
  await assert.rejects(() => getPublications(client), /rls/);
});
