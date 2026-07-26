/**
 * Storage upload helpers — thin wrappers over supabase-js's Storage API,
 * following data/db.js's "accept an injected client" convention so the
 * network calls stay mockable under `node --test` (see storage.test.js).
 * Both buckets' RLS (admin-write-only, keyed on the `admins` table — see
 * db/schema.sql) is already live server-side; these functions just make the
 * call, they don't re-implement the policy.
 */

import { getClient } from "./db.js";

export const SITE_MEDIA_BUCKET = "site-media";
export const CV_UPLOADS_BUCKET = "cv-uploads";

// Fixed object path in the private bucket — overwritten on every upload, no
// versioning (matches the plan's D section). The backend's `fetch-cv`
// command downloads this exact path with the secret key.
export const CV_UPLOAD_PATH = "cv/current.docx";

/**
 * Upload `file` into the public `site-media` bucket at `path` (e.g.
 * "people/jane-doe.jpg"), overwriting any existing object at that path, and
 * return its public URL. Building `path` (slug, extension) is the caller's
 * job — this just performs the upload + URL lookup.
 */
export async function uploadToSiteMedia(file, path, client = getClient()) {
  const bucket = client.storage.from(SITE_MEDIA_BUCKET);
  const { error } = await bucket.upload(path, file, { upsert: true });
  if (error) throw error;
  const { data } = bucket.getPublicUrl(path);
  return data.publicUrl;
}

/**
 * Upload the lab's CV docx into the private `cv-uploads` bucket at the fixed
 * `cv/current.docx` path (overwritten each time, no versioning). No public
 * URL to return — the bucket is private, read only by the backend's secret
 * key (`hct-manager fetch-cv`).
 */
export async function uploadToCvUploads(file, client = getClient()) {
  const { error } = await client.storage
    .from(CV_UPLOADS_BUCKET)
    .upload(CV_UPLOAD_PATH, file, { upsert: true });
  if (error) throw error;
}
