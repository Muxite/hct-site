/**
 * GitHub REST calls for the admin-jobs workflow — the only two things the
 * job endpoints do once a caller has been proven to be an admin: dispatch a
 * run, and read a run's status.
 *
 * The workflow file name is a hardcoded constant here, never taken from the
 * request: the endpoints exist to run *this* one workflow, and a caller must
 * never be able to steer the PAT at some other workflow, repo or ref. The
 * PAT itself (`GITHUB_PAT`) is a Vercel Project Settings env var — plain,
 * never `VITE_`-prefixed, so Vite can never inline it into the browser
 * bundle — and nothing GitHub returns is passed through to the caller
 * verbatim.
 */

import { HttpError } from "./http.js";

const GITHUB_API = "https://api.github.com";

/** The workflow this endpoint pair exists to run (.github/workflows/). */
export const WORKFLOW_FILE = "admin-jobs.yml";

/** The `job_type` values admin-jobs.yml's workflow_dispatch input accepts. */
export const JOB_TYPES = Object.freeze(["cv-sync", "style-regen"]);

// GitHub owners/repos are alphanumerics plus `-`, `_` and `.`; a git ref adds
// `/`. Both are validated even though they come from our own env, so a
// fat-fingered setting can't produce a surprising request path.
const REPO_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;
const REF_RE = /^[A-Za-z0-9._/-]+$/;

const REQUEST_TIMEOUT_MS = 10_000;

/**
 * Read `GITHUB_PAT` / `GITHUB_REPO` (`owner/repo`) / optional `GITHUB_REF`
 * (default `main`). A missing or malformed setting is a 500 with a generic
 * message — it never names the variable at fault.
 */
export function githubConfig(env = process.env) {
  const token = env.GITHUB_PAT;
  const repo = env.GITHUB_REPO;
  const ref = env.GITHUB_REF || "main";
  if (!token || !repo || !REPO_RE.test(repo) || !REF_RE.test(ref)) {
    throw new HttpError(500, "Admin jobs are not configured on the server.");
  }
  return { token, repo, ref };
}

async function githubFetch(path, { token, method = "GET", body } = {}, fetchImpl = fetch) {
  const headers = {
    accept: "application/vnd.github+json",
    authorization: `Bearer ${token}`,
    "x-github-api-version": "2022-11-28",
    // GitHub rejects API requests without a User-Agent.
    "user-agent": "hct-site-admin-jobs",
  };
  if (body !== undefined) headers["content-type"] = "application/json";
  let response;
  try {
    response = await fetchImpl(`${GITHUB_API}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new HttpError(502, "Couldn't reach GitHub.");
  }
  return response;
}

/**
 * Fire admin-jobs.yml's workflow_dispatch with `job_type`.
 *
 * `jobType` MUST already have been validated against `JOB_TYPES` by the
 * caller; this asserts it again rather than trusting that, because it is the
 * function actually holding the PAT.
 */
export async function dispatchWorkflow(jobType, cfg, fetchImpl = fetch) {
  if (!JOB_TYPES.includes(jobType)) {
    throw new HttpError(400, "Unknown job type.");
  }
  const response = await githubFetch(
    `/repos/${cfg.repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    { token: cfg.token, method: "POST", body: { ref: cfg.ref, inputs: { job_type: jobType } } },
    fetchImpl,
  );
  // A successful dispatch is 204 No Content, and returns no run id — the run
  // has to be found afterwards by listing runs (see latestWorkflowRun).
  if (response.status !== 204) {
    throw new HttpError(502, `GitHub refused the job (HTTP ${response.status}).`);
  }
}

/** The fields of a workflow run the admin UI actually shows. */
export function summarizeRun(run) {
  if (!run) return null;
  return {
    id: run.id,
    status: run.status ?? null,
    conclusion: run.conclusion ?? null,
    created_at: run.created_at ?? null,
    updated_at: run.updated_at ?? null,
    html_url: run.html_url ?? null,
    run_number: run.run_number ?? null,
  };
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    throw new HttpError(502, "GitHub returned an unreadable response.");
  }
}

/** The most recent workflow_dispatch run of admin-jobs.yml, or null. */
export async function latestWorkflowRun(cfg, fetchImpl = fetch) {
  const response = await githubFetch(
    `/repos/${cfg.repo}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=1&event=workflow_dispatch`,
    { token: cfg.token },
    fetchImpl,
  );
  if (!response.ok) {
    throw new HttpError(502, `GitHub couldn't list the runs (HTTP ${response.status}).`);
  }
  const payload = await readJson(response);
  const runs = Array.isArray(payload?.workflow_runs) ? payload.workflow_runs : [];
  return summarizeRun(runs[0] ?? null);
}

/**
 * One specific run by id. `runId` must already be a validated positive
 * integer — it is re-checked here because it lands in a request path.
 */
export async function workflowRun(runId, cfg, fetchImpl = fetch) {
  if (!Number.isSafeInteger(runId) || runId <= 0) {
    throw new HttpError(400, "run_id must be a positive integer.");
  }
  const response = await githubFetch(
    `/repos/${cfg.repo}/actions/runs/${runId}`,
    { token: cfg.token },
    fetchImpl,
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new HttpError(502, `GitHub couldn't read that run (HTTP ${response.status}).`);
  }
  return summarizeRun(await readJson(response));
}
