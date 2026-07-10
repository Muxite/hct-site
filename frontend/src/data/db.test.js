import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getPaperSamples,
  getPublicationsPage,
  getPublicationsBySlugs,
  isMissingSamplesTable,
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
