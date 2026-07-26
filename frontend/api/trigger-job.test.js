import { test } from "node:test";
import assert from "node:assert/strict";

import { handleTriggerJob } from "./trigger-job.js";
import { AdminAuthError } from "./_lib/verifyAdmin.js";

// Endpoint-level counterpart to _lib/verifyAdmin.test.js: these assert the
// *ordering* property the plan calls load-bearing — that nothing reaches
// GitHub (the thing holding the PAT and spending CI minutes) unless the
// admin check resolved first, and that `job_type` is checked against a fixed
// allowlist rather than forwarded.

const ENV = { GITHUB_PAT: "ghp_test", GITHUB_REPO: "Muxite/hct-site" };
const RUN = {
  id: 500,
  status: "completed",
  conclusion: "success",
  created_at: "2026-07-26T10:00:00Z",
  updated_at: "2026-07-26T10:05:00Z",
  html_url: "https://github.com/Muxite/hct-site/actions/runs/500",
  run_number: 7,
};

/** Records every GitHub call; a test that expects none asserts `calls` is []. */
function fakeGithub({ runs = [RUN], dispatchStatus = 204, listStatus = 200 } = {}) {
  const calls = [];
  async function impl(url, init = {}) {
    calls.push({ url, method: init.method || "GET", headers: init.headers, body: init.body });
    if (url.includes("/dispatches")) {
      return new Response(null, { status: dispatchStatus });
    }
    if (url.includes("/runs?")) {
      if (listStatus !== 200) return new Response("nope", { status: listStatus });
      return new Response(JSON.stringify({ workflow_runs: runs }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("unexpected", { status: 404 });
  }
  return { impl, calls };
}

/** A stand-in for verifyAdmin with the same contract: throw, or return a user. */
function fakeVerify(okToken = "admin-token") {
  const seen = [];
  const verify = async (token) => {
    seen.push(token);
    if (typeof token !== "string" || token.trim() === "") {
      throw new AdminAuthError("missing_token", "No access token was supplied.");
    }
    if (token !== okToken) {
      throw new AdminAuthError("not_admin", "This account isn't on the admin allowlist.");
    }
    return { id: "admin-user-id" };
  };
  return { verify, seen };
}

function post(body, { method = "POST", contentType = "application/json" } = {}) {
  const headers = contentType ? { "content-type": contentType } : {};
  const init = { method, headers };
  if (method !== "GET" && method !== "HEAD") init.body = JSON.stringify(body ?? {});
  return new Request("https://hct.example/api/trigger-job", init);
}

test("a non-POST request is refused and never reaches GitHub", async () => {
  const gh = fakeGithub();
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(
    new Request("https://hct.example/api/trigger-job", { method: "GET" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 405);
  assert.deepEqual(gh.calls, []);
});

test("a non-JSON body is refused (a cross-site form can't reach this endpoint)", async () => {
  const gh = fakeGithub();
  const { verify, seen } = fakeVerify();
  const res = await handleTriggerJob(post({ job_type: "cv-sync" }, { contentType: "text/plain" }), {
    verify,
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 415);
  assert.deepEqual(seen, []);
  assert.deepEqual(gh.calls, []);
});

test("no token at all -> 403, and nothing is dispatched", async () => {
  const gh = fakeGithub();
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(post({ job_type: "cv-sync" }), {
    verify,
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 403);
  assert.equal((await res.json()).reason, "missing_token");
  assert.deepEqual(gh.calls, [], "a tokenless caller must not reach GitHub");
});

test("a garbage/expired token -> 403, and nothing is dispatched", async () => {
  const gh = fakeGithub();
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(
    post({ job_type: "cv-sync", supabase_access_token: "not-a-real-token" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 403);
  assert.deepEqual(gh.calls, []);
});

test("a valid session for a non-admin user -> 403, and nothing is dispatched", async () => {
  const gh = fakeGithub();
  const verify = async () => {
    throw new AdminAuthError("not_admin", "This account isn't on the admin allowlist.");
  };
  const res = await handleTriggerJob(
    post({ job_type: "cv-sync", supabase_access_token: "real-session-of-a-visitor" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 403);
  assert.equal((await res.json()).reason, "not_admin");
  assert.deepEqual(gh.calls, []);
});

test("an unrecognised job_type is rejected before it can reach GitHub", async () => {
  const rejected = [
    "cv-sync-please",
    "CV-SYNC",
    "cv-sync ",
    " cv-sync",
    "cv-sync;style-regen",
    "../../../other-workflow.yml",
    "",
    undefined,
    null,
    42,
    ["cv-sync"],
    { job_type: "cv-sync" },
  ];
  for (const jobType of rejected) {
    const gh = fakeGithub();
    const { verify } = fakeVerify();
    const res = await handleTriggerJob(
      post({ job_type: jobType, supabase_access_token: "admin-token" }),
      { verify, env: ENV, fetchImpl: gh.impl },
    );
    assert.equal(res.status, 400, `expected 400 for job_type ${JSON.stringify(jobType)}`);
    assert.deepEqual(gh.calls, [], `job_type ${JSON.stringify(jobType)} must not reach GitHub`);
  }
});

test("an admin dispatching cv-sync hits exactly the admin-jobs.yml dispatch endpoint", async () => {
  const gh = fakeGithub();
  const { verify, seen } = fakeVerify();
  const res = await handleTriggerJob(
    post({ job_type: "cv-sync", supabase_access_token: "admin-token" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );

  assert.equal(res.status, 202);
  const payload = await res.json();
  assert.equal(payload.ok, true);
  assert.equal(payload.job_type, "cv-sync");
  assert.equal(payload.previous_run_id, 500);
  assert.ok(Date.parse(payload.dispatched_at) > 0);
  assert.deepEqual(seen, ["admin-token"]);

  const dispatch = gh.calls.find((c) => c.url.includes("/dispatches"));
  assert.equal(
    dispatch.url,
    "https://api.github.com/repos/Muxite/hct-site/actions/workflows/admin-jobs.yml/dispatches",
  );
  assert.equal(dispatch.method, "POST");
  assert.equal(dispatch.headers.authorization, "Bearer ghp_test");
  assert.deepEqual(JSON.parse(dispatch.body), { ref: "main", inputs: { job_type: "cv-sync" } });
});

test("style-regen is the other accepted job type", async () => {
  const gh = fakeGithub();
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(
    post({ job_type: "style-regen", supabase_access_token: "admin-token" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 202);
  const dispatch = gh.calls.find((c) => c.url.includes("/dispatches"));
  assert.deepEqual(JSON.parse(dispatch.body), { ref: "main", inputs: { job_type: "style-regen" } });
});

test("GITHUB_REF overrides the dispatched ref", async () => {
  const gh = fakeGithub();
  const { verify } = fakeVerify();
  await handleTriggerJob(post({ job_type: "cv-sync", supabase_access_token: "admin-token" }), {
    verify,
    env: { ...ENV, GITHUB_REF: "feat/variants-gallery" },
    fetchImpl: gh.impl,
  });
  const dispatch = gh.calls.find((c) => c.url.includes("/dispatches"));
  assert.equal(JSON.parse(dispatch.body).ref, "feat/variants-gallery");
});

test("a missing/malformed GitHub config is a 500 that names nothing", async () => {
  for (const env of [{}, { GITHUB_PAT: "x" }, { GITHUB_PAT: "x", GITHUB_REPO: "not-a-repo" }]) {
    const gh = fakeGithub();
    const { verify } = fakeVerify();
    const res = await handleTriggerJob(
      post({ job_type: "cv-sync", supabase_access_token: "admin-token" }),
      { verify, env, fetchImpl: gh.impl },
    );
    assert.equal(res.status, 500);
    const body = await res.json();
    assert.doesNotMatch(body.error, /GITHUB_PAT|GITHUB_REPO/);
    assert.deepEqual(gh.calls, []);
  }
});

test("a GitHub refusal surfaces as a 502 without leaking GitHub's response", async () => {
  const gh = fakeGithub({ dispatchStatus: 403 });
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(
    post({ job_type: "cv-sync", supabase_access_token: "admin-token" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 502);
  assert.doesNotMatch((await res.json()).error, /ghp_test/);
});

test("a failed pre-dispatch run listing doesn't block the dispatch", async () => {
  const gh = fakeGithub({ listStatus: 500 });
  const { verify } = fakeVerify();
  const res = await handleTriggerJob(
    post({ job_type: "cv-sync", supabase_access_token: "admin-token" }),
    { verify, env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 202);
  assert.equal((await res.json()).previous_run_id, null);
  assert.ok(gh.calls.some((c) => c.url.includes("/dispatches")));
});

test("the default export is a fetch handler that forwards only the request", async () => {
  const mod = (await import("./trigger-job.js")).default;
  assert.equal(typeof mod.fetch, "function");
  assert.equal(mod.fetch.length, 1, "extra platform arguments must not become injectable deps");
});
