import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getPaperSamples,
  getPublicationsPage,
  getPublicationsBySlugs,
  isMissingSamplesTable,
  isMockMode,
  getAdminStatus,
} from "./db.js";

function samplesClient(result) {
  const builder = {
    select() {
      return builder;
    },
    order() {
      return Promise.resolve(result);
    },
  };
  return { from: () => builder };
}

/** A `select().eq().maybeSingle()` chain — the shape `getAdminStatus` uses. */
function singleClient(result) {
  const calls = [];
  const builder = {
    select(cols) {
      calls.push(["select", cols]);
      return builder;
    },
    eq(col, val) {
      calls.push(["eq", col, val]);
      return builder;
    },
    maybeSingle() {
      return Promise.resolve(result);
    },
  };
  return { client: { from: () => builder }, calls };
}

/** Records the calls made against the query builder, resolving to `result`. */
function recordingClient(result) {
  const calls = [];
  const builder = {
    select(cols, opts) {
      calls.push(["select", cols, opts]);
      return builder;
    },
    order(col, opts) {
      calls.push(["order", col, opts]);
      return builder;
    },
    range(from, to) {
      calls.push(["range", from, to]);
      return Promise.resolve(result);
    },
    in(col, vals) {
      calls.push(["in", col, vals]);
      return Promise.resolve(result);
    },
  };
  return { client: { from: () => builder }, calls };
}

test("isMissingSamplesTable recognizes the optional table schema-cache miss", () => {
  assert.equal(
    isMissingSamplesTable({
      code: "PGRST205",
      message: "Could not find the table 'public.paper_samples' in the schema cache",
    }),
    true,
  );
});

test("getPaperSamples returns empty rows when the optional table is absent", async () => {
  const rows = await getPaperSamples(
    samplesClient({
      data: null,
      error: {
        code: "PGRST205",
        message: "Could not find the table 'public.paper_samples' in the schema cache",
      },
    }),
  );

  assert.deepEqual(rows, []);
});

test("getPaperSamples still throws non-schema Supabase errors", async () => {
  const error = { code: "42501", message: "permission denied for table paper_samples" };
  await assert.rejects(
    getPaperSamples(
      samplesClient({
        data: null,
        error,
      }),
    ),
    error,
  );
});

test("getPublicationsPage requests a bounded range and returns the total count", async () => {
  const { client, calls } = recordingClient({
    data: [{ slug: "a" }, { slug: "b" }],
    error: null,
    count: 551,
  });
  const { rows, total } = await getPublicationsPage({ offset: 30, limit: 30 }, client);
  assert.equal(rows.length, 2);
  assert.equal(total, 551);
  const rangeCall = calls.find((c) => c[0] === "range");
  assert.deepEqual(rangeCall, ["range", 30, 59]);
});

test("getPublicationsBySlugs short-circuits on an empty list without querying", async () => {
  const { client, calls } = recordingClient({ data: [{ slug: "a" }], error: null });
  const rows = await getPublicationsBySlugs([], client);
  assert.deepEqual(rows, []);
  assert.equal(calls.length, 0);
});

test("getPublicationsBySlugs filters by the given slugs", async () => {
  const { client, calls } = recordingClient({
    data: [{ slug: "a" }, { slug: "b" }],
    error: null,
  });
  const rows = await getPublicationsBySlugs(["a", "b"], client);
  assert.equal(rows.length, 2);
  assert.deepEqual(
    calls.find((c) => c[0] === "in"),
    ["in", "slug", ["a", "b"]],
  );
});

// --- isMockMode --------------------------------------------------------------
// The guard `context/AdminContext.jsx` must check before any `supabase.auth.*`
// call. AdminContext itself is a .jsx component with no render harness in this
// repo (no jsdom/@testing-library — see db.test.js/feedbackTarget.test.js for
// the established "fake minimal DOM" pattern used instead), so this is the
// piece of the mock-mode guard that's actually exercised at the unit level;
// that AdminContext wires every auth call behind it is verified by reading
// the source, not by an automated test.
test("isMockMode is true when VITE_MOCK is truthy", () => {
  assert.equal(isMockMode({ VITE_MOCK: "1" }), true);
  assert.equal(isMockMode({ VITE_MOCK: true }), true);
});

test("isMockMode is false when VITE_MOCK is unset or empty", () => {
  assert.equal(isMockMode({}), false);
  assert.equal(isMockMode({ VITE_MOCK: "" }), false);
  assert.equal(isMockMode({ VITE_MOCK: undefined }), false);
});

// --- getAdminStatus ------------------------------------------------------------
test("getAdminStatus returns false without querying when there is no user id", async () => {
  const { client, calls } = singleClient({ data: null, error: null });
  assert.equal(await getAdminStatus(null, client), false);
  assert.equal(await getAdminStatus(undefined, client), false);
  assert.equal(calls.length, 0);
});

test("getAdminStatus returns true when the admins row is visible", async () => {
  const { client, calls } = singleClient({ data: { user_id: "u1" }, error: null });
  assert.equal(await getAdminStatus("u1", client), true);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "user_id", "u1"],
  );
});

test("getAdminStatus returns false when RLS hides the row (signed-in non-admin)", async () => {
  const { client } = singleClient({ data: null, error: null });
  assert.equal(await getAdminStatus("u2", client), false);
});

test("getAdminStatus still throws a non-RLS Supabase error", async () => {
  const error = { code: "500", message: "boom" };
  const { client } = singleClient({ data: null, error });
  await assert.rejects(getAdminStatus("u3", client), error);
});
