import { test } from "node:test";
import assert from "node:assert/strict";

import { matchRoute } from "./router.js";

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
