/**
 * POST /api/trigger-job — start one of the admin-jobs.yml CI jobs.
 *
 * Body: `{ job_type: "cv-sync" | "style-regen", supabase_access_token }`.
 *
 * This is a public URL. Everything it can do is gated on `verifyAdmin()`
 * resolving first (see _lib/verifyAdmin.js); the ordering below is
 * load-bearing, not stylistic:
 *
 *   1. reject anything that isn't a POST         (no side effect)
 *   2. parse the JSON body                       (needed to read the token)
 *   3. await verifyAdmin(...)                    <- the gate
 *   4. only now: validate job_type
 *   5. only now: read GITHUB_PAT and call GitHub
 *
 * Nothing is logged, no config is read, and no outbound request is made
 * before step 3 finishes. `job_type` in particular is not even looked at
 * until the caller is proven to be an admin, and is then checked against a
 * fixed allowlist — an arbitrary string is never forwarded to GitHub.
 */

import { verifyAdmin } from "./_lib/verifyAdmin.js";
import { errorResponse, json, readJsonBody, requireMethod, HttpError } from "./_lib/http.js";
import { JOB_TYPES, dispatchWorkflow, githubConfig, latestWorkflowRun } from "./_lib/github.js";

export async function handleTriggerJob(request, deps = {}) {
  const { verify = verifyAdmin, env = process.env, fetchImpl = fetch } = deps;
  try {
    requireMethod(request, "POST");
    const body = await readJsonBody(request);

    // --- the gate. Nothing below runs unless this resolves. ---
    await verify(body.supabase_access_token);

    const jobType = body.job_type;
    if (typeof jobType !== "string" || !JOB_TYPES.includes(jobType)) {
      throw new HttpError(400, `job_type must be one of: ${JOB_TYPES.join(", ")}.`);
    }

    const cfg = githubConfig(env);

    // workflow_dispatch answers 204 with no run id, so the run has to be
    // recognised afterwards by "the latest run isn't the one that was latest
    // before". Best-effort: if this read fails, the dispatch still goes
    // ahead and the client falls back to comparing timestamps.
    let previousRunId = null;
    try {
      previousRunId = (await latestWorkflowRun(cfg, fetchImpl))?.id ?? null;
    } catch {
      previousRunId = null;
    }

    const dispatchedAt = new Date().toISOString();
    await dispatchWorkflow(jobType, cfg, fetchImpl);

    return json(202, {
      ok: true,
      job_type: jobType,
      dispatched_at: dispatchedAt,
      previous_run_id: previousRunId,
    });
  } catch (err) {
    return errorResponse(err);
  }
}

// Passing only `request` through is deliberate: the platform may call
// `fetch` with extra arguments, and none of them may ever land in `deps`
// (which is a test seam holding the auth check itself).
export default { fetch: (request) => handleTriggerJob(request) };
