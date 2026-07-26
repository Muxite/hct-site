import { test } from "node:test";
import assert from "node:assert/strict";

import { matchRoute, pathFromHash } from "./router.js";

const ROUTES = [
  ["/", "home"],
  ["/projects/:slug", "project"],
  ["/papers/:slug", "paper"],
];

test("matchRoute matches the root path", () => {
  const got = matchRoute("/", ROUTES);
  assert.equal(got.value, "home");
  assert.deepEqual(got.params, {});
});

test("matchRoute captures a :param segment", () => {
  const got = matchRoute("/projects/brain2speech", ROUTES);
  assert.equal(got.value, "project");
  assert.deepEqual(got.params, { slug: "brain2speech" });
});

test("matchRoute decodes URI-encoded params", () => {
  const got = matchRoute("/papers/fels%202022-x", ROUTES);
  assert.deepEqual(got.params, { slug: "fels 2022-x" });
});

test("matchRoute returns null when nothing matches", () => {
  assert.equal(matchRoute("/nope/at/all", ROUTES), null);
});

test("matchRoute requires exact segment count", () => {
  assert.equal(matchRoute("/projects", ROUTES), null);
  assert.equal(matchRoute("/projects/a/b", ROUTES), null);
});

// --- pathFromHash ------------------------------------------------------------
test("pathFromHash strips the leading # and query string", () => {
  assert.equal(pathFromHash("#/projects/foo?x=1"), "/projects/foo");
  assert.equal(pathFromHash("/admin"), "/admin");
});

test("pathFromHash defaults to / for an empty hash", () => {
  assert.equal(pathFromHash(""), "/");
  assert.equal(pathFromHash("#"), "/");
  assert.equal(pathFromHash(undefined), "/");
});

test("pathFromHash treats a bare Supabase implicit-flow callback as /", () => {
  assert.equal(pathFromHash("#access_token=abc123&expires_in=3600&type=magiclink"), "/");
});

test("pathFromHash treats a callback appended after our own route as /", () => {
  // supabase-js appends token params onto whatever redirect hash we gave it,
  // so a `#/admin` login link can come back as `#/admin&access_token=...`.
  assert.equal(pathFromHash("#/admin&access_token=abc123&type=magiclink"), "/");
});

test("pathFromHash treats an auth error callback as / too", () => {
  assert.equal(pathFromHash("#error=access_denied&error_description=expired"), "/");
});

test("pathFromHash does not false-positive on an unrelated query param", () => {
  assert.equal(pathFromHash("#/papers/foo?access_token_ref=1"), "/papers/foo");
});
