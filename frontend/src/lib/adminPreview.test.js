import { test } from "node:test";
import assert from "node:assert/strict";

import { shouldForceAdminPreview } from "./adminPreview.js";

// --- shouldForceAdminPreview -------------------------------------------------
// `context/AdminContext.jsx` computes its ADMIN_PREVIEW constant once at
// module load from `import.meta.env.VITE_ADMIN_PREVIEW` / `.DEV` — both
// build-time constants baked in at bundle time, not something a running test
// can flip. This is the pure guard pulled out of that computation so the
// decision itself (not the env plumbing around it) is unit-tested; see
// db.test.js's `isMockMode` tests for the same pattern applied to VITE_MOCK.

test("is inert (false) when the dev guard is false, even with the env flag set — this is what keeps a real production build safe", () => {
  assert.equal(shouldForceAdminPreview({ envFlag: "1", isDev: false }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: true, isDev: false }), false);
  // `vite build`'s default NODE_ENV=production makes `import.meta.env.DEV`
  // false regardless of --mode, so this is the exact shape of "someone left
  // VITE_ADMIN_PREVIEW set and shipped a real production build".
  assert.equal(shouldForceAdminPreview({ envFlag: "1", isDev: undefined }), false);
});

test("forces preview only once both the env flag AND the dev guard are true", () => {
  assert.equal(shouldForceAdminPreview({ envFlag: "1", isDev: true }), true);
  assert.equal(shouldForceAdminPreview({ envFlag: true, isDev: true }), true);
});

test("is inert when the env flag is unset or empty, even under a dev build", () => {
  assert.equal(shouldForceAdminPreview({ envFlag: undefined, isDev: true }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: "", isDev: true }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: false, isDev: true }), false);
});

// Regression: a naive `Boolean(envFlag)` would treat the *string* "false"
// (what a `.env` line reading `VITE_ADMIN_PREVIEW=false` actually produces —
// every Vite env var is a string) as truthy, silently turning preview mode
// ON for someone who explicitly wrote "false" to turn it off. `shouldForceAdminPreview`
// must only accept the exact strings "1"/"true" (or a real boolean `true`).
test("treats the string \"false\" (and other non-'1'/'true' strings) as OFF, not truthy", () => {
  assert.equal(shouldForceAdminPreview({ envFlag: "false", isDev: true }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: "0", isDev: true }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: "no", isDev: true }), false);
  assert.equal(shouldForceAdminPreview({ envFlag: "yes", isDev: true }), false);
});

test("accepts the exact strings \"1\" and \"true\" (and boolean true) as ON", () => {
  assert.equal(shouldForceAdminPreview({ envFlag: "1", isDev: true }), true);
  assert.equal(shouldForceAdminPreview({ envFlag: "true", isDev: true }), true);
  assert.equal(shouldForceAdminPreview({ envFlag: true, isDev: true }), true);
});

test("defaults to false when called with no arguments", () => {
  assert.equal(shouldForceAdminPreview(), false);
});
