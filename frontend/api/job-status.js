/**
 * POST /api/job-status — read an admin-jobs.yml run's status.
 *
 * Body: `{ supabase_access_token, run_id? }`. With no `run_id` it answers
 * with the most recent workflow_dispatch run of admin-jobs.yml, which is
 * what the admin page polls (~3s) after triggering a job.
 *
 * POST rather than GET on purpose: the access token belongs in a body, not
 * in a query string that lands in access logs, browser history and referrers.
 *
 * Same load-bearing ordering as trigger-job.js — method check, parse body,
 * `await verifyAdmin(...)`, and only then validate `run_id` and touch
 * GitHub. Run status is not public: it exposes the repo's CI activity and is
 * gated behind exactly the same admin check as triggering.
 */

import { verifyAdmin } from "./_lib/verifyAdmin.js";
import { errorResponse, json, readJsonBody, requireMethod, HttpError } from "./_lib/http.js";
import { githubConfig, latestWorkflowRun, workflowRun } from "./_lib/github.js";

export async function handleJobStatus(request, deps = {}) {
  const { verify = verifyAdmin, env = process.env, fetchImpl = fetch } = deps;
  try {
    requireMethod(request, "POST");
    const body = await readJsonBody(request);

    // --- the gate. Nothing below runs unless this resolves. ---
    await verify(body.supabase_access_token);

    // `run_id` reaches a request path, so it is accepted only as a positive
    // integer (or absent) — never as an arbitrary string.
    const rawRunId = body.run_id;
    let runId = null;
    if (rawRunId !== undefined && rawRunId !== null) {
      if (typeof rawRunId !== "number" && typeof rawRunId !== "string") {
        throw new HttpError(400, "run_id must be a positive integer.");
      }
      runId = typeof rawRunId === "number" ? rawRunId : Number(rawRunId.trim());
      if (!Number.isSafeInteger(runId) || runId <= 0) {
        throw new HttpError(400, "run_id must be a positive integer.");
      }
    }

    const cfg = githubConfig(env);
    const run = runId === null
      ? await latestWorkflowRun(cfg, fetchImpl)
      : await workflowRun(runId, cfg, fetchImpl);

    return json(200, { run });
  } catch (err) {
    return errorResponse(err);
  }
}

// Only `request` is forwarded — see the same note in trigger-job.js.
export default { fetch: (request) => handleJobStatus(request) };
