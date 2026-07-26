import { test } from "node:test";
import assert from "node:assert/strict";

import {
  groupByYear,
  splitByKind,
  typeLabel,
  formatAuthors,
  emailLabel,
  isImageFile,
  slugify,
  photoPath,
  projectImagePath,
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

test("isImageFile accepts a real image file (EditableImage.jsx's happy path)", () => {
  assert.equal(isImageFile({ name: "photo.jpg", type: "image/jpeg" }), true);
  assert.equal(isImageFile({ name: "photo.png", type: "image/png" }), true);
  assert.equal(isImageFile({ name: "photo.webp", type: "image/webp" }), true);
});

test("isImageFile rejects a non-image file even if it slipped past accept=\"image/*\"", () => {
  assert.equal(isImageFile({ name: "cv.docx", type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }), false);
  assert.equal(isImageFile({ name: "notes.txt", type: "text/plain" }), false);
});

test("isImageFile rejects missing/malformed input without throwing", () => {
  assert.equal(isImageFile(null), false);
  assert.equal(isImageFile(undefined), false);
  assert.equal(isImageFile({}), false);
  assert.equal(isImageFile({ name: "mystery", type: "" }), false);
});

// --- slugify (People.jsx's photo-path builder) -------------------------------
test("slugify lowercases and hyphenates a plain name", () => {
  assert.equal(slugify("Sidney Fels"), "sidney-fels");
});

test("slugify collapses runs of non-alphanumerics into a single hyphen", () => {
  assert.equal(slugify("Jane  O'Brien-Smith!!"), "jane-o-brien-smith");
});

test("slugify trims leading/trailing hyphens", () => {
  assert.equal(slugify("  -Ana-  "), "ana");
});

test("slugify returns an empty string for missing/empty input without throwing", () => {
  assert.equal(slugify(""), "");
  assert.equal(slugify(null), "");
  assert.equal(slugify(undefined), "");
});

// --- photoPath (People.jsx's + SiteHome.jsx's shared photo-upload path) ------
test("photoPath slugifies the name and keeps the file's extension", () => {
  assert.equal(photoPath("Sidney Fels", { name: "headshot.PNG" }), "people/sidney-fels.png");
});

test("photoPath falls back to jpg when the file name has no extension", () => {
  assert.equal(photoPath("Jane Doe", { name: "" }), "people/jane-doe.jpg");
});

// --- projectImagePath (SiteHome.jsx's project hero-image upload path) -------
test("projectImagePath uses the project's own slug and the file's extension", () => {
  assert.equal(projectImagePath("muvr", { name: "hero.jpeg" }), "projects/muvr.jpeg");
});

test("projectImagePath falls back to jpg when the file name has no extension", () => {
  assert.equal(projectImagePath("muvr", { name: "" }), "projects/muvr.jpg");
});
