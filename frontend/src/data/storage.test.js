import { test } from "node:test";
import assert from "node:assert/strict";

import {
  uploadToSiteMedia,
  uploadToCvUploads,
  SITE_MEDIA_BUCKET,
  CV_UPLOADS_BUCKET,
  CV_UPLOAD_PATH,
} from "./storage.js";
import { DOCX_MIME } from "../lib/format.js";

/** Records from()/upload()/getPublicUrl() calls against a fake Storage client. */
function fakeStorageClient({ uploadError = null, publicUrl = "https://x/site-media/foo.jpg" } = {}) {
  const calls = [];
  const bucketApi = {
    upload(path, file, opts) {
      calls.push(["upload", path, file, opts]);
      return Promise.resolve({ data: uploadError ? null : { path }, error: uploadError });
    },
    getPublicUrl(path) {
      calls.push(["getPublicUrl", path]);
      return { data: { publicUrl } };
    },
  };
  const client = {
    storage: {
      from(bucket) {
        calls.push(["from", bucket]);
        return bucketApi;
      },
    },
  };
  return { client, calls };
}

test("uploadToSiteMedia uploads to the public bucket with upsert and returns the public URL", async () => {
  const { client, calls } = fakeStorageClient({ publicUrl: "https://x/site-media/people/a.jpg" });
  const file = { name: "a.jpg" };
  const url = await uploadToSiteMedia(file, "people/a.jpg", client);

  assert.match(url, /^https:\/\/x\/site-media\/people\/a\.jpg\?v=\d+$/);
  assert.deepEqual(calls[0], ["from", SITE_MEDIA_BUCKET]);
  assert.deepEqual(calls[1], ["upload", "people/a.jpg", file, { upsert: true }]);
  assert.deepEqual(calls[2], ["getPublicUrl", "people/a.jpg"]);
});

test("uploadToSiteMedia returns a different URL each time so a replaced image isn't served from cache", async () => {
  // The storage path is deterministic, so replacing a .jpg with a .jpg gives
  // back the identical public URL — the DB value wouldn't change, React would
  // render the same src, and the CDN's 1h cacheControl would keep serving the
  // old bytes. The `?v=` stamp is what breaks that.
  const opts = { publicUrl: "https://x/site-media/people/a.jpg" };
  const first = await uploadToSiteMedia({ name: "a.jpg" }, "people/a.jpg", fakeStorageClient(opts).client);
  await new Promise((r) => setTimeout(r, 2));
  const second = await uploadToSiteMedia({ name: "a.jpg" }, "people/a.jpg", fakeStorageClient(opts).client);
  assert.notEqual(first, second);
});

test("uploadToSiteMedia keeps an existing query string when stamping the URL", async () => {
  const { client } = fakeStorageClient({ publicUrl: "https://x/site-media/a.jpg?token=abc" });
  const url = await uploadToSiteMedia({ name: "a.jpg" }, "a.jpg", client);
  assert.match(url, /^https:\/\/x\/site-media\/a\.jpg\?token=abc&v=\d+$/);
});

test("uploadToSiteMedia throws on a Storage error without calling getPublicUrl", async () => {
  const error = { message: "not authorized" };
  const { client, calls } = fakeStorageClient({ uploadError: error });
  await assert.rejects(uploadToSiteMedia({ name: "a.jpg" }, "people/a.jpg", client), error);
  assert.equal(calls.some((c) => c[0] === "getPublicUrl"), false);
});

test("uploadToCvUploads uploads to the private bucket at the fixed path", async () => {
  const { client, calls } = fakeStorageClient();
  const file = { name: "cv.docx" };
  await uploadToCvUploads(file, client);

  assert.deepEqual(calls[0], ["from", CV_UPLOADS_BUCKET]);
  assert.deepEqual(calls[1], ["upload", CV_UPLOAD_PATH, file, { upsert: true }]);
});

test("uploadToCvUploads pins the docx content type a picker left blank", async () => {
  // The cv-uploads bucket only accepts the docx MIME type (db/schema.sql), and
  // Storage reads that type off the blob itself — an untyped .docx would go up
  // as application/octet-stream and be rejected.
  const { client, calls } = fakeStorageClient();
  await uploadToCvUploads(new Blob(["PK"], { type: "" }), client);
  assert.equal(calls[1][2].type, DOCX_MIME);
});

test("uploadToCvUploads leaves an already-correct docx blob alone", async () => {
  const { client, calls } = fakeStorageClient();
  const file = new Blob(["PK"], { type: DOCX_MIME });
  await uploadToCvUploads(file, client);
  assert.equal(calls[1][2], file, "no needless re-wrap/copy of the file");
});

test("uploadToCvUploads throws on a Storage error", async () => {
  const error = { message: "denied" };
  const { client } = fakeStorageClient({ uploadError: error });
  await assert.rejects(uploadToCvUploads({ name: "cv.docx" }, client), error);
});
