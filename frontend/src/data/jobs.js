/**
 * Client side of the admin CI jobs — the browser half of api/trigger-job.js
 * and api/job-status.js.
 *
 * Nothing here is a security boundary: both endpoints re-verify the access
 * token server-side with the Supabase SECRET key before doing anything (see
 * api/_lib/verifyAdmin.js). The `JOB_TYPES` check below is for fast feedback
 * and a clearer error message, not protection — the server does not trust it.
 *
 * `fetch` is injectable on both calls, matching the "accept an injected
 * client" convention in data/db.js and data/storage.js, so the helpers stay
 * testable under `node --test` with no network.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export const JOB_TYPES = Object.freeze(["cv-sync", "style-regen"]);

const TRIGGER_ENDPOINT = "/api/trigger-job";
const STATUS_ENDPOINT = "/api/job-status";

/** How often the admin page re-checks a queued/running job. */
export const POLL_INTERVAL_MS = 3000;
/** Give up watching after this long — `cv-sync` re-runs the whole pipeline. */
export const POLL_TIMEOUT_MS = 20 * 60 * 1000;
/** Consecutive failed polls tolerated before the UI reports an error. */
export const MAX_POLL_FAILURES = 3;
/** Slack between Vercel's clock and GitHub's when falling back to timestamps. */
const CLOCK_SLACK_MS = 5000;

function errorText(err) {
  return String(err?.message || err || "Unknown error");
}

async function postJson(url, payload, fetchImpl) {
  let response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("Couldn't reach the server.");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new Error(data?.error || `Request failed (HTTP ${response.status}).`);
  }
  return data ?? {};
}

function requireToken(accessToken) {
  if (typeof accessToken !== "string" || accessToken.trim() === "") {
    throw new Error("You're signed out — sign in again to run this.");
  }
}

/**
 * Ask CI to run `jobType`. Resolves to
 * `{ ok, job_type, dispatched_at, previous_run_id }` — the last two are what
 * `isOurRun()` uses to tell the new run apart from whatever ran last.
 */
export async function triggerJob(jobType, accessToken, fetchImpl = fetch) {
  requireToken(accessToken);
  if (!JOB_TYPES.includes(jobType)) {
    throw new Error(`Unknown job type "${jobType}".`);
  }
  return postJson(
    TRIGGER_ENDPOINT,
    { job_type: jobType, supabase_access_token: accessToken },
    fetchImpl,
  );
}

/**
 * Read a run's status. `runId` may be null/undefined for "whichever run is
 * most recent". Resolves to `{ run }`, where `run` is null if there's none.
 */
export async function getJobStatus(runId, accessToken, fetchImpl = fetch) {
  requireToken(accessToken);
  const payload = { supabase_access_token: accessToken };
  if (runId !== null && runId !== undefined) payload.run_id = runId;
  return postJson(STATUS_ENDPOINT, payload, fetchImpl);
}

/**
 * Is this the run we just triggered, or the previous one still sitting at
 * the top of the list?
 *
 * `workflow_dispatch` returns no run id, and GitHub takes a few seconds to
 * create the run, so a naive "show the latest run" would flash the *previous*
 * job's result — reporting "done" for something that hasn't started. Run ids
 * increase, so a run newer than the one that was latest before the dispatch
 * is ours. When that pre-dispatch id couldn't be read, fall back to
 * comparing creation time against the dispatch time.
 */
export function isOurRun(run, { previousRunId = null, dispatchedAt = 0 } = {}) {
  if (!run || typeof run.id !== "number") return false;
  if (previousRunId !== null && previousRunId !== undefined) {
    return run.id > previousRunId;
  }
  const created = Date.parse(run.created_at ?? "");
  if (Number.isNaN(created)) return false;
  return created >= dispatchedAt - CLOCK_SLACK_MS;
}

/** Human label for a run, used by the admin page's status line. */
export function runLabel(phase, run) {
  switch (phase) {
    case "triggering":
      return "Starting…";
    case "queued":
      return "Queued — waiting for CI to pick it up…";
    case "running":
      return run?.status === "queued" ? "Queued on GitHub…" : "Running…";
    case "done":
      return "Done.";
    case "failed":
      return "The job failed.";
    case "timeout":
      return "Still going after 20 minutes — check the run on GitHub.";
    default:
      return "";
  }
}

/**
 * Trigger a job and follow it to completion.
 *
 * Returns `{ phase, run, error, start, reset }`, where phase moves
 * idle -> triggering -> queued -> running -> done | failed | timeout | error.
 * Polling runs on a ~3s timer only while a job is outstanding and stops on
 * completion, on repeated failures, at the timeout, and on unmount — the
 * `alive` flag + cleanup shape every page component in this app already uses.
 */
export function useJobRunner(accessToken) {
  const [state, setState] = useState({ phase: "idle", run: null, error: "" });
  const aliveRef = useRef(true);
  const timerRef = useRef(null);
  // Null whenever no job is outstanding; polling stops as soon as it is.
  const watchRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const poll = useCallback(async () => {
    const watch = watchRef.current;
    if (!watch || !aliveRef.current) return;
    try {
      const { run } = await getJobStatus(null, accessToken);
      if (!aliveRef.current || watchRef.current !== watch) return;
      watch.failures = 0;
      if (isOurRun(run, watch)) {
        if (run.status === "completed") {
          watchRef.current = null;
          setState({
            phase: run.conclusion === "success" ? "done" : "failed",
            run,
            error: "",
          });
          return;
        }
        setState({ phase: "running", run, error: "" });
      } else {
        setState((prev) => ({ ...prev, phase: "queued", run: null }));
      }
    } catch (err) {
      if (!aliveRef.current || watchRef.current !== watch) return;
      watch.failures += 1;
      if (watch.failures >= MAX_POLL_FAILURES) {
        watchRef.current = null;
        setState((prev) => ({ ...prev, phase: "error", error: errorText(err) }));
        return;
      }
    }
    if (Date.now() - watch.startedAt > POLL_TIMEOUT_MS) {
      watchRef.current = null;
      setState((prev) => ({ ...prev, phase: "timeout" }));
      return;
    }
    timerRef.current = setTimeout(() => pollRef.current?.(), POLL_INTERVAL_MS);
  }, [accessToken]);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  const start = useCallback(
    async (jobType) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      watchRef.current = null;
      setState({ phase: "triggering", run: null, error: "" });
      try {
        const result = await triggerJob(jobType, accessToken);
        if (!aliveRef.current) return;
        watchRef.current = {
          previousRunId: result?.previous_run_id ?? null,
          dispatchedAt: Date.parse(result?.dispatched_at ?? "") || Date.now(),
          startedAt: Date.now(),
          failures: 0,
        };
        setState({ phase: "queued", run: null, error: "" });
        timerRef.current = setTimeout(() => pollRef.current?.(), POLL_INTERVAL_MS);
      } catch (err) {
        if (!aliveRef.current) return;
        watchRef.current = null;
        setState({ phase: "error", run: null, error: errorText(err) });
      }
    },
    [accessToken],
  );

  const reset = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    watchRef.current = null;
    setState({ phase: "idle", run: null, error: "" });
  }, []);

  return { ...state, start, reset };
}
