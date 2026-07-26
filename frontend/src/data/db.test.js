import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getPaperSamples,
  getPublicationsPage,
  getPublicationsBySlugs,
  isMissingSamplesTable,
  isMockMode,
  getAdminStatus,
  updateSiteContent,
  insertPerson,
  updatePerson,
  personProjectSlugs,
  deletePerson,
  updateProject,
  updatePublication,
  getStyleProfile,
  updateStyleProfileExcerpt,
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

// --- updateSiteContent --------------------------------------------------------
/** An `upsert(payload, opts)` call — the shape `updateSiteContent` uses. */
function upsertClient(result) {
  const calls = [];
  const builder = {
    upsert(payload, opts) {
      calls.push(["upsert", payload, opts]);
      return Promise.resolve(result);
    },
  };
  return { client: { from: () => builder }, calls };
}

test("updateSiteContent upserts the key/value row keyed on `key`", async () => {
  const { client, calls } = upsertClient({ error: null });
  await updateSiteContent("vision", { title: "Vision", text: "New text" }, client);
  assert.deepEqual(calls[0], [
    "upsert",
    { key: "vision", value: { title: "Vision", text: "New text" } },
    { onConflict: "key" },
  ]);
});

test("updateSiteContent throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = upsertClient({ error });
  await assert.rejects(updateSiteContent("vision", { text: "x" }, client), error);
});

// --- insertPerson / updatePerson (people CRUD) --------------------------------
/** An `insert()`/`update()` -> `.eq()`? -> `select()` -> `maybeSingle()` chain
 * — the shape both insertPerson (no `.eq()`) and updatePerson (with `.eq()`)
 * use. */
function writeSelectClient(result) {
  const calls = [];
  const builder = {
    insert(payload) {
      calls.push(["insert", payload]);
      return builder;
    },
    update(payload) {
      calls.push(["update", payload]);
      return builder;
    },
    eq(col, val) {
      calls.push(["eq", col, val]);
      return builder;
    },
    select(cols) {
      calls.push(["select", cols]);
      return builder;
    },
    maybeSingle() {
      return Promise.resolve(result);
    },
  };
  return { client: { from: () => builder }, calls };
}

test("insertPerson inserts the row and returns the selected result", async () => {
  const row = { name: "Jane Doe", role: "Grad student", kind: "current" };
  const { client, calls } = writeSelectClient({ data: row, error: null });
  const result = await insertPerson(row, client);
  assert.deepEqual(result, row);
  assert.deepEqual(calls[0], ["insert", row]);
  assert.equal(calls.some((c) => c[0] === "select"), true);
});

test("insertPerson surfaces a duplicate name as a friendly error", async () => {
  const { client } = writeSelectClient({
    data: null,
    error: { code: "23505", message: "duplicate key value violates unique constraint" },
  });
  await assert.rejects(insertPerson({ name: "Jane Doe" }, client), /already exists/);
});

test("insertPerson still throws a non-duplicate Supabase error", async () => {
  const error = { code: "42501", message: "permission denied" };
  const { client } = writeSelectClient({ data: null, error });
  await assert.rejects(insertPerson({ name: "Jane Doe" }, client), error);
});

test("updatePerson updates by name and returns the selected result", async () => {
  const row = { name: "Jane Doe", role: "Postdoc" };
  const { client, calls } = writeSelectClient({ data: row, error: null });
  const result = await updatePerson("Jane Doe", { role: "Postdoc" }, client);
  assert.deepEqual(result, row);
  assert.deepEqual(calls[0], ["update", { role: "Postdoc" }]);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "name", "Jane Doe"],
  );
});

test("updatePerson throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = writeSelectClient({ data: null, error });
  await assert.rejects(updatePerson("Jane Doe", { role: "x" }, client), error);
});

// --- getStyleProfile / updateStyleProfileExcerpt (exemplar/style calibration) -
test("getStyleProfile returns the row filtered to the fixed 'default' id", async () => {
  const row = { source_excerpt: "Some raw text.", profile_text: "Crisp, active voice." };
  const { client, calls } = singleClient({ data: row, error: null });
  const result = await getStyleProfile(client);
  assert.deepEqual(result, row);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "id", "default"],
  );
});

test("getStyleProfile returns null when no row exists yet", async () => {
  const { client } = singleClient({ data: null, error: null });
  assert.equal(await getStyleProfile(client), null);
});

test("getStyleProfile throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = singleClient({ data: null, error });
  await assert.rejects(getStyleProfile(client), error);
});

test("updateStyleProfileExcerpt upserts the fixed 'default' row's source_excerpt", async () => {
  const { client, calls } = upsertClient({ error: null });
  await updateStyleProfileExcerpt("New exemplar text.", client);
  assert.deepEqual(calls[0], [
    "upsert",
    { id: "default", source_excerpt: "New exemplar text." },
    { onConflict: "id" },
  ]);
});

test("updateStyleProfileExcerpt throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = upsertClient({ error });
  await assert.rejects(updateStyleProfileExcerpt("x", client), error);
});

// --- updateProject (Gallery's project-hero-image CRUD) ------------------------
test("updateProject updates by slug and returns the selected result", async () => {
  const row = { slug: "muvr", title: "MUVR", hero_image: "https://x/hero.jpg" };
  const { client, calls } = writeSelectClient({ data: row, error: null });
  const result = await updateProject("muvr", { hero_image: "https://x/hero.jpg" }, client);
  assert.deepEqual(result, row);
  assert.deepEqual(calls[0], ["update", { hero_image: "https://x/hero.jpg" }]);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "slug", "muvr"],
  );
});

test("updateProject throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = writeSelectClient({ data: null, error });
  await assert.rejects(updateProject("muvr", { hero_image: "x" }, client), error);
});

// --- updatePublication (ProjectPage/PaperPage summary + image CRUD) -----------
test("updatePublication updates by slug and returns the selected result", async () => {
  const row = { slug: "muvr-paper", title: "MUVR Paper", summary_plain: "New plain summary" };
  const { client, calls } = writeSelectClient({ data: row, error: null });
  const result = await updatePublication("muvr-paper", { summary_plain: "New plain summary" }, client);
  assert.deepEqual(result, row);
  assert.deepEqual(calls[0], ["update", { summary_plain: "New plain summary" }]);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "slug", "muvr-paper"],
  );
});

test("updatePublication throws on a Supabase error", async () => {
  const error = { message: "not authorized" };
  const { client } = writeSelectClient({ data: null, error });
  await assert.rejects(updatePublication("muvr-paper", { image: "x" }, client), error);
});

// --- personProjectSlugs / deletePerson (delete-guard) -------------------------
/** A `select().eq()` chain resolving directly (no maybeSingle) — used for the
 * project_people membership check. */
function projectPeopleClient(result) {
  const calls = [];
  const builder = {
    select(cols) {
      calls.push(["select", cols]);
      return builder;
    },
    eq(col, val) {
      calls.push(["eq", col, val]);
      return Promise.resolve(result);
    },
  };
  return { client: { from: () => builder }, calls };
}

test("personProjectSlugs returns the linked project slugs", async () => {
  const { client, calls } = projectPeopleClient({
    data: [{ project_slug: "brain2speech" }, { project_slug: "other-proj" }],
    error: null,
  });
  const slugs = await personProjectSlugs("Jane Doe", client);
  assert.deepEqual(slugs, ["brain2speech", "other-proj"]);
  assert.deepEqual(
    calls.find((c) => c[0] === "eq"),
    ["eq", "person_name", "Jane Doe"],
  );
});

test("personProjectSlugs returns an empty list when unlinked", async () => {
  const { client } = projectPeopleClient({ data: [], error: null });
  assert.deepEqual(await personProjectSlugs("Jane Doe", client), []);
});

test("personProjectSlugs throws on a Supabase error", async () => {
  const error = { message: "boom" };
  const { client } = projectPeopleClient({ data: null, error });
  await assert.rejects(personProjectSlugs("Jane Doe", client), error);
});

/** Routes `.from(table)` to a project_people-membership builder or a
 * people-delete builder, so deletePerson's two-step query/guard is testable
 * end to end against one fake client. */
function deletePersonClient({ linkedSlugs = [], deleteError = null }) {
  const calls = [];
  const projectPeopleBuilder = {
    select(cols) {
      calls.push(["projectPeople.select", cols]);
      return projectPeopleBuilder;
    },
    eq(col, val) {
      calls.push(["projectPeople.eq", col, val]);
      return Promise.resolve({
        data: linkedSlugs.map((s) => ({ project_slug: s })),
        error: null,
      });
    },
  };
  const peopleBuilder = {
    delete() {
      calls.push(["people.delete"]);
      return peopleBuilder;
    },
    eq(col, val) {
      calls.push(["people.eq", col, val]);
      return Promise.resolve({ error: deleteError });
    },
  };
  return {
    client: {
      from: (table) => (table === "project_people" ? projectPeopleBuilder : peopleBuilder),
    },
    calls,
  };
}

test("deletePerson deletes when the person has no project links", async () => {
  const { client, calls } = deletePersonClient({ linkedSlugs: [] });
  await deletePerson("Jane Doe", client);
  assert.equal(calls.some((c) => c[0] === "people.delete"), true);
  assert.deepEqual(
    calls.find((c) => c[0] === "people.eq"),
    ["people.eq", "name", "Jane Doe"],
  );
});

test("deletePerson blocks with a clear message when the person is still linked to a project", async () => {
  const { client, calls } = deletePersonClient({ linkedSlugs: ["brain2speech"] });
  await assert.rejects(deletePerson("Jane Doe", client), /brain2speech/);
  assert.equal(calls.some((c) => c[0] === "people.delete"), false);
});

test("deletePerson blocks and lists multiple linked projects in the message", async () => {
  const { client } = deletePersonClient({ linkedSlugs: ["brain2speech", "other-proj"] });
  await assert.rejects(deletePerson("Jane Doe", client), /brain2speech.*other-proj/s);
});

test("deletePerson throws the underlying error when the delete itself fails", async () => {
  const error = { message: "not authorized" };
  const { client } = deletePersonClient({ linkedSlugs: [], deleteError: error });
  await assert.rejects(deletePerson("Jane Doe", client), error);
});
