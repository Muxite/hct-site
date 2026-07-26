import { test } from "node:test";
import assert from "node:assert/strict";

import {
  PEOPLE_KIND_SYNC_CAVEAT,
  ADD_PERSON_SYNC_CAVEAT,
  personFieldsFromDraft,
  nextSortOrder,
  addPersonWithPhoto,
} from "./usePersonEditor.js";

// `usePersonEditor`/`useAddPersonForm` themselves call React's `useState` and
// so can't be invoked outside a component render — this codebase has no
// jsdom/@testing-library render harness (confirmed by earlier tasks' own
// reports), so the two hooks aren't unit-tested directly here. What's
// covered below is everything extractable as a plain function: the shared
// caveat text (single-sourced now, so People.jsx and SiteHome.jsx can't
// silently drift), the draft -> payload mapping, the sort_order computation,
// and the insert-with-photo orchestration (with injected fakes standing in
// for the real network calls, same convention data/db.js's tests use).

test("PEOPLE_KIND_SYNC_CAVEAT / ADD_PERSON_SYNC_CAVEAT are the single source of the sync caveat copy", () => {
  assert.match(PEOPLE_KIND_SYNC_CAVEAT, /people\.yaml/);
  assert.match(PEOPLE_KIND_SYNC_CAVEAT, /CV\/people sync/);
  assert.match(ADD_PERSON_SYNC_CAVEAT, /people\.yaml/);
  assert.match(ADD_PERSON_SYNC_CAVEAT, /delete and re-add/);
});

test("personFieldsFromDraft trims and null-coalesces blank fields", () => {
  const fields = personFieldsFromDraft({
    role: "  Postdoc  ",
    email: "  ",
    bio: "",
    kind: "alumni",
  });
  assert.deepEqual(fields, { role: "Postdoc", email: null, bio: null, kind: "alumni" });
});

test("personFieldsFromDraft passes non-blank fields through untouched", () => {
  const fields = personFieldsFromDraft({
    role: "PhD Student",
    email: "jane@ubc.ca",
    bio: "Works on speech.",
    kind: "current",
  });
  assert.deepEqual(fields, {
    role: "PhD Student",
    email: "jane@ubc.ca",
    bio: "Works on speech.",
    kind: "current",
  });
});

test("nextSortOrder is one past the current max", () => {
  assert.equal(nextSortOrder([{ sort_order: 1 }, { sort_order: 4 }, { sort_order: 2 }]), 5);
});

test("nextSortOrder treats a missing sort_order as 0", () => {
  assert.equal(nextSortOrder([{ sort_order: 3 }, {}]), 4);
});

test("nextSortOrder returns 1 for an empty or missing roster", () => {
  assert.equal(nextSortOrder([]), 1);
  assert.equal(nextSortOrder(undefined), 1);
});

test("addPersonWithPhoto uploads the photo, stamps sort_order, and inserts", async () => {
  const uploadCalls = [];
  const insertCalls = [];
  const upload = async (file, path) => {
    uploadCalls.push([file, path]);
    return "https://cdn.example/people/jane-doe.jpg";
  };
  const insert = async (payload) => {
    insertCalls.push(payload);
    return { ...payload, bio: null };
  };

  const file = { name: "headshot.jpg", type: "image/jpeg" };
  const created = await addPersonWithPhoto(
    { name: "Jane Doe", role: "Grad student", email: null, kind: "current" },
    file,
    [{ sort_order: 2 }, { sort_order: 5 }],
    { insert, upload },
  );

  assert.deepEqual(uploadCalls[0], [file, "people/jane-doe.jpg"]);
  assert.equal(insertCalls[0].photo, "https://cdn.example/people/jane-doe.jpg");
  assert.equal(insertCalls[0].sort_order, 6);
  assert.equal(created.sort_order, 6);
  assert.equal(created.photo, "https://cdn.example/people/jane-doe.jpg");
});

test("addPersonWithPhoto skips the upload entirely when there's no file", async () => {
  let uploadCalled = false;
  const upload = async () => {
    uploadCalled = true;
    return "unused";
  };
  const insert = async (payload) => ({ ...payload, bio: null });

  const created = await addPersonWithPhoto(
    { name: "Jane Doe", role: null, email: null, kind: "current" },
    null,
    [],
    { insert, upload },
  );

  assert.equal(uploadCalled, false);
  assert.equal(created.photo, null);
  assert.equal(created.sort_order, 1);
});

test("addPersonWithPhoto falls back to the built payload when insert returns no row", async () => {
  const insert = async () => null;
  const created = await addPersonWithPhoto(
    { name: "Jane Doe", role: null, email: null, kind: "current" },
    null,
    [],
    { insert, upload: async () => null },
  );
  assert.equal(created.name, "Jane Doe");
  assert.equal(created.bio, null);
});
