import { test } from "node:test";
import assert from "node:assert/strict";

import {
  uploadToSiteMedia,
  uploadToCvUploads,
  SITE_MEDIA_BUCKET,
  CV_UPLOADS_BUCKET,
  CV_UPLOAD_PATH,
} from "./storage.js";

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

  assert.equal(url, "https://x/site-media/people/a.jpg");
  assert.deepEqual(calls[0], ["from", SITE_MEDIA_BUCKET]);
  assert.deepEqual(calls[1], ["upload", "people/a.jpg", file, { upsert: true }]);
  assert.deepEqual(calls[2], ["getPublicUrl", "people/a.jpg"]);
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

test("uploadToCvUploads throws on a Storage error", async () => {
  const error = { message: "denied" };
  const { client } = fakeStorageClient({ uploadError: error });
  await assert.rejects(uploadToCvUploads({ name: "cv.docx" }, client), error);
});
