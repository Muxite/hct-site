import { test } from "node:test";
import assert from "node:assert/strict";

import {
  JOB_TYPES,
  triggerJob,
  getJobStatus,
  isOurRun,
  runLabel,
  POLL_INTERVAL_MS,
} from "./jobs.js";

// `useJobRunner` calls React hooks and so can't run outside a render — this
// codebase has no jsdom harness (see hooks/usePersonEditor.test.js's note),
// so what's covered here is everything extractable as a plain function: the
// two request helpers (with an injected fetch, as data/db.js's tests do) and
// the run-freshness rule the hook leans on.

function fakeFetch(responder) {
  const calls = [];
  async function impl(url, init) {
    calls.push({ url, init, body: init?.body ? JSON.parse(init.body) : null });
    return responder(url, init);
  }
  return { impl, calls };
}

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("triggerJob posts the job type and token to /api/trigger-job", async () => {
  const fetcher = fakeFetch(() =>
    jsonResponse(202, { ok: true, job_type: "cv-sync", dispatched_at: "x", previous_run_id: 3 }),
  );
  const result = await triggerJob("cv-sync", "token-abc", fetcher.impl);

  assert.equal(result.previous_run_id, 3);
  assert.equal(fetcher.calls[0].url, "/api/trigger-job");
  assert.equal(fetcher.calls[0].init.method, "POST");
  assert.deepEqual(fetcher.calls[0].body, {
    job_type: "cv-sync",
    supabase_access_token: "token-abc",
  });
});

test("triggerJob refuses an unknown job type without a request", async () => {
  const fetcher = fakeFetch(() => jsonResponse(202, {}));
  await assert.rejects(() => triggerJob("rm-rf", "token-abc", fetcher.impl), /Unknown job type/);
  assert.deepEqual(fetcher.calls, []);
});

test("triggerJob refuses a missing token without a request", async () => {
  const fetcher = fakeFetch(() => jsonResponse(202, {}));
  for (const token of [undefined, null, "", "  "]) {
    await assert.rejects(() => triggerJob("cv-sync", token, fetcher.impl), /signed out/);
  }
  assert.deepEqual(fetcher.calls, []);
});

test("triggerJob surfaces the server's error message on a rejection", async () => {
  const fetcher = fakeFetch(() =>
    jsonResponse(403, { error: "This account isn't on the admin allowlist.", reason: "not_admin" }),
  );
  await assert.rejects(() => triggerJob("cv-sync", "token", fetcher.impl), /admin allowlist/);
});

test("triggerJob falls back to a status-code message when the body isn't JSON", async () => {
  const fetcher = fakeFetch(() => new Response("gateway blew up", { status: 502 }));
  await assert.rejects(() => triggerJob("cv-sync", "token", fetcher.impl), /HTTP 502/);
});

test("getJobStatus omits run_id when asking for the latest run", async () => {
  const fetcher = fakeFetch(() => jsonResponse(200, { run: null }));
  await getJobStatus(null, "token-abc", fetcher.impl);
  assert.equal(fetcher.calls[0].url, "/api/job-status");
  assert.deepEqual(fetcher.calls[0].body, { supabase_access_token: "token-abc" });
});

test("getJobStatus passes a run_id through when given one", async () => {
  const fetcher = fakeFetch(() => jsonResponse(200, { run: { id: 9 } }));
  const { run } = await getJobStatus(9, "token-abc", fetcher.impl);
  assert.equal(run.id, 9);
  assert.deepEqual(fetcher.calls[0].body, { supabase_access_token: "token-abc", run_id: 9 });
});

test("isOurRun tells the newly dispatched run apart from the previous one", () => {
  const watch = { previousRunId: 100, dispatchedAt: Date.parse("2026-07-26T12:00:00Z") };
  assert.equal(isOurRun({ id: 100, created_at: "2026-07-26T11:00:00Z" }, watch), false);
  assert.equal(isOurRun({ id: 101, created_at: "2026-07-26T12:00:05Z" }, watch), true);
  assert.equal(isOurRun({ id: 99, created_at: "2026-07-26T10:00:00Z" }, watch), false);
  assert.equal(isOurRun(null, watch), false);
});

test("isOurRun falls back to creation time when there was no previous run id", () => {
  const dispatchedAt = Date.parse("2026-07-26T12:00:00Z");
  const watch = { previousRunId: null, dispatchedAt };
  assert.equal(isOurRun({ id: 7, created_at: "2026-07-26T12:00:04Z" }, watch), true);
  assert.equal(isOurRun({ id: 7, created_at: "2026-07-26T11:30:00Z" }, watch), false);
  assert.equal(isOurRun({ id: 7, created_at: "nonsense" }, watch), false);
  assert.equal(isOurRun({ id: 7 }, watch), false);
});

test("runLabel describes each phase without inventing one for idle", () => {
  assert.equal(runLabel("idle", null), "");
  assert.match(runLabel("triggering", null), /Starting/);
  assert.match(runLabel("queued", null), /Queued/);
  assert.match(runLabel("running", { status: "in_progress" }), /Running/);
  assert.match(runLabel("done", {}), /Done/);
  assert.match(runLabel("failed", {}), /failed/);
  assert.match(runLabel("timeout", {}), /check the run/);
});

test("the two job types match admin-jobs.yml's workflow_dispatch choices", () => {
  assert.deepEqual([...JOB_TYPES], ["cv-sync", "style-regen"]);
  assert.equal(POLL_INTERVAL_MS, 3000);
});
