/**
 * Tiny request/response helpers shared by the two job endpoints. Nothing
 * here is job-specific — it exists so trigger-job.js and job-status.js don't
 * each grow their own slightly-different body parser (the one place where a
 * subtle difference between the two would be a security difference).
 */

/** An HTTP-shaped refusal. Thrown by the helpers, caught by the endpoints. */
export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** JSON response with caching explicitly off — these are never cacheable. */
export function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

/**
 * Turn a thrown error into a response without leaking internals. Only
 * `AdminAuthError`/`HttpError` (both of which carry a deliberate, reviewed
 * message) reach the caller; anything else becomes a bare 500.
 */
export function errorResponse(err) {
  const status = Number.isInteger(err?.status) ? err.status : 500;
  if (err?.name === "AdminAuthError") {
    return json(status, { error: err.message, reason: err.reason });
  }
  if (err?.name === "HttpError") {
    return json(status, { error: err.message });
  }
  return json(500, { error: "Something went wrong." });
}

const MAX_BODY_BYTES = 8 * 1024;

/**
 * Parse a JSON object body.
 *
 * `application/json` is *required*, which also means a cross-site HTML form
 * can't reach these endpoints at all: forms can only send text/plain,
 * urlencoded or multipart, so anything else is preflighted and blocked by
 * the browser. (Auth here is a bearer token in the body, not a cookie, so
 * CSRF isn't the threat model either way — this is just one less way in.)
 */
export async function readJsonBody(request, maxBytes = MAX_BODY_BYTES) {
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes("application/json")) {
    throw new HttpError(415, "Send a JSON body with content-type: application/json.");
  }
  const raw = await request.text();
  if (raw.length > maxBytes) {
    throw new HttpError(413, "Request body is too large.");
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new HttpError(400, "Request body isn't valid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new HttpError(400, "Request body must be a JSON object.");
  }
  return parsed;
}

/** Reject anything that isn't the one method an endpoint accepts. */
export function requireMethod(request, method) {
  if (request.method !== method) {
    throw new HttpError(405, `Use ${method}.`);
  }
}
