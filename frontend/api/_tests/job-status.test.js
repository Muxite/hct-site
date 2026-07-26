// Tests for api/'s serverless functions. They live under `_tests/`, not
// beside the files they cover, because Vercel turns *every* file directly
// under `api/` into a public route — `api/trigger-job.test.js` would deploy
// as a live `/api/trigger-job.test` endpoint. Only paths containing a `/_`
// segment are excluded (see `_lib/verifyAdmin.js`'s note), so anything that
// isn't an endpoint belongs under an underscore directory. `node --test`
// discovers them here exactly as it did before.
import { test } from "node:test";
import assert from "node:assert/strict";

import { handleJobStatus } from "../job-status.js";
import { AdminAuthError } from "../_lib/verifyAdmin.js";

// Run status isn't public either — it exposes the repo's CI activity — so
// this endpoint is gated by the same check as trigger-job.js, and `run_id`
// (which lands in a GitHub request path) is accepted only as a positive
// integer.

const ENV = { GITHUB_PAT: "ghp_test", GITHUB_REPO: "Muxite/hct-site" };
const RUN = {
  id: 501,
  status: "in_progress",
  conclusion: null,
  created_at: "2026-07-26T11:00:00Z",
  updated_at: "2026-07-26T11:01:00Z",
  html_url: "https://github.com/Muxite/hct-site/actions/runs/501",
  run_number: 8,
  // Fields the summary deliberately drops rather than forwarding wholesale:
  head_commit: { message: "secret-ish internals" },
};

function fakeGithub({ runs = [RUN], listStatus = 200, runStatus = 200 } = {}) {
  const calls = [];
  async function impl(url, init = {}) {
    calls.push({ url, method: init.method || "GET", headers: init.headers });
    if (url.includes("/runs?")) {
      if (listStatus !== 200) return new Response("nope", { status: listStatus });
      return new Response(JSON.stringify({ workflow_runs: runs }), { status: 200 });
    }
    if (/\/actions\/runs\/\d+$/.test(url)) {
      if (runStatus !== 200) return new Response("nope", { status: runStatus });
      return new Response(JSON.stringify(runs[0] ?? null), { status: 200 });
    }
    return new Response("unexpected", { status: 404 });
  }
  return { impl, calls };
}

function fakeVerify(okToken = "admin-token") {
  return async (token) => {
    if (typeof token !== "string" || token.trim() === "") {
      throw new AdminAuthError("missing_token", "No access token was supplied.");
    }
    if (token !== okToken) {
      throw new AdminAuthError("not_admin", "This account isn't on the admin allowlist.");
    }
    return { id: "admin-user-id" };
  };
}

function post(body, { method = "POST", contentType = "application/json" } = {}) {
  const headers = contentType ? { "content-type": contentType } : {};
  const init = { method, headers };
  if (method !== "GET" && method !== "HEAD") init.body = JSON.stringify(body ?? {});
  return new Request("https://hct.example/api/job-status", init);
}

test("a non-POST request is refused (the token belongs in a body, not a URL)", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(
    new Request("https://hct.example/api/job-status", { method: "GET" }),
    { verify: fakeVerify(), env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 405);
  assert.deepEqual(gh.calls, []);
});

test("no token -> 403, and GitHub is never called", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(post({}), {
    verify: fakeVerify(),
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 403);
  assert.equal((await res.json()).reason, "missing_token");
  assert.deepEqual(gh.calls, []);
});

test("a bad token -> 403, and GitHub is never called", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(post({ supabase_access_token: "nope" }), {
    verify: fakeVerify(),
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 403);
  assert.deepEqual(gh.calls, []);
});

test("a non-integer run_id is rejected before any GitHub call", async () => {
  for (const runId of ["abc", "12; DROP TABLE", 1.5, -3, 0, "", "  ", true, {}, [], "1e400"]) {
    const gh = fakeGithub();
    const res = await handleJobStatus(
      post({ supabase_access_token: "admin-token", run_id: runId }),
      { verify: fakeVerify(), env: ENV, fetchImpl: gh.impl },
    );
    assert.equal(res.status, 400, `expected 400 for run_id ${JSON.stringify(runId)}`);
    assert.deepEqual(gh.calls, [], `run_id ${JSON.stringify(runId)} must not reach GitHub`);
  }
});

test("an admin with no run_id gets the latest workflow_dispatch run", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(post({ supabase_access_token: "admin-token" }), {
    verify: fakeVerify(),
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 200);
  const { run } = await res.json();
  assert.equal(run.id, 501);
  assert.equal(run.status, "in_progress");
  assert.equal(run.conclusion, null);
  assert.equal(run.html_url, RUN.html_url);
  assert.equal(run.head_commit, undefined, "only the summarised fields are returned");
  assert.equal(
    gh.calls[0].url,
    "https://api.github.com/repos/Muxite/hct-site/actions/workflows/admin-jobs.yml/runs?per_page=1&event=workflow_dispatch",
  );
  assert.equal(gh.calls[0].headers.authorization, "Bearer ghp_test");
});

test("an admin with a run_id reads exactly that run", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(
    post({ supabase_access_token: "admin-token", run_id: 501 }),
    { verify: fakeVerify(), env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 200);
  assert.equal(gh.calls[0].url, "https://api.github.com/repos/Muxite/hct-site/actions/runs/501");
});

test("a numeric-string run_id is accepted and normalised", async () => {
  const gh = fakeGithub();
  const res = await handleJobStatus(
    post({ supabase_access_token: "admin-token", run_id: " 501 " }),
    { verify: fakeVerify(), env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 200);
  assert.equal(gh.calls[0].url, "https://api.github.com/repos/Muxite/hct-site/actions/runs/501");
});

test("no runs yet reads as null rather than an error", async () => {
  const gh = fakeGithub({ runs: [] });
  const res = await handleJobStatus(post({ supabase_access_token: "admin-token" }), {
    verify: fakeVerify(),
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 200);
  assert.equal((await res.json()).run, null);
});

test("a deleted run reads as null", async () => {
  const gh = fakeGithub({ runStatus: 404 });
  const res = await handleJobStatus(
    post({ supabase_access_token: "admin-token", run_id: 999 }),
    { verify: fakeVerify(), env: ENV, fetchImpl: gh.impl },
  );
  assert.equal(res.status, 200);
  assert.equal((await res.json()).run, null);
});

test("a GitHub outage surfaces as 502 without leaking the PAT", async () => {
  const gh = fakeGithub({ listStatus: 500 });
  const res = await handleJobStatus(post({ supabase_access_token: "admin-token" }), {
    verify: fakeVerify(),
    env: ENV,
    fetchImpl: gh.impl,
  });
  assert.equal(res.status, 502);
  assert.doesNotMatch((await res.json()).error, /ghp_test/);
});

test("with no deps override, the real verifyAdmin is the one that runs", async () => {
  // Same reasoning as trigger-job.test.js: pins that the production default
  // for `verify` really is verifyAdmin, not just that a gate is callable.
  const noToken = await handleJobStatus(post({}));
  assert.equal(noToken.status, 403);
  assert.deepEqual(await noToken.json(), {
    error: "No access token was supplied.",
    reason: "missing_token",
  });

  const malformed = await handleJobStatus(post({ supabase_access_token: "token with a space" }));
  assert.equal(malformed.status, 403);
  assert.equal((await malformed.json()).reason, "invalid_token");
});

test("the default export is a fetch handler that forwards only the request", async () => {
  const mod = (await import("../job-status.js")).default;
  assert.equal(typeof mod.fetch, "function");
  assert.equal(mod.fetch.length, 1);
});
