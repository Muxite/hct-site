import { test } from "node:test";
import assert from "node:assert/strict";

import {
  groupByYear,
  splitByKind,
  typeLabel,
  formatAuthors,
  emailLabel,
} from "./format.js";

test("groupByYear sorts years newest first", () => {
  const got = groupByYear([
    { title: "a", year: 2019 },
    { title: "b", year: 2023 },
    { title: "c", year: 2021 },
  ]);
  assert.deepEqual(
    got.map(([y]) => y),
    [2023, 2021, 2019],
  );
});

test("groupByYear buckets multiple entries per year", () => {
  const got = groupByYear([
    { title: "a", year: 2023 },
    { title: "b", year: 2023 },
    { title: "c", year: 2021 },
  ]);
  assert.equal(got[0][0], 2023);
  assert.equal(got[0][1].length, 2);
});

test("splitByKind sets aside the matching kind", () => {
  const [current, alumni] = splitByKind(
    [
      { name: "A", kind: "current" },
      { name: "B", kind: "alumni" },
      { name: "C" },
    ],
    "alumni",
  );
  assert.deepEqual(current.map((p) => p.name), ["A", "C"]);
  assert.deepEqual(alumni.map((p) => p.name), ["B"]);
});

test("typeLabel maps known types and falls back to Misc", () => {
  assert.equal(typeLabel("inproceedings"), "Conference");
  assert.equal(typeLabel("nonsense"), "Misc");
});

test("formatAuthors joins with semicolons", () => {
  assert.equal(formatAuthors(["A Person", "B Other"]), "A Person; B Other");
  assert.equal(formatAuthors([]), "");
});

test("emailLabel obfuscates the @", () => {
  assert.equal(emailLabel("a@b.com"), "a [at] b.com");
});
