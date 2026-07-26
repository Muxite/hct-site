/**
 * Server-side admin verification for the /api job endpoints.
 *
 * These endpoints are PUBLIC URLs — anyone who finds them can POST to them.
 * The only thing standing between the open internet and a CI run that spends
 * the project's LLM budget is this file, so it is deliberately paranoid and
 * fails closed on every path that isn't an unambiguous "yes, this is a
 * logged-in user whose id is in `admins`".
 *
 * Why the token is re-checked here at all: the browser's own `isAdmin` flag
 * (context/AdminContext.jsx) is advisory UI state, and the RLS policies that
 * really protect Supabase don't apply to GitHub's API. A caller could send
 * any JSON they like. So the access token is validated against Supabase
 * itself, with the SECRET key (`SB_SEC_KEY`) — which lives only in Vercel
 * Project Settings, is never `VITE_`-prefixed, and therefore never reaches
 * the browser bundle.
 *
 * Files under `api/` whose path contains a `/_` segment are not turned into
 * endpoints by Vercel (`fileName.includes('/_')` in @vercel/fs-detectors'
 * detect-builders), so `_lib/` is a shared-helper directory, not a route.
 */

import { createClient } from "@supabase/supabase-js";

/**
 * A refusal to act. `reason` is a coarse machine-readable category (safe to
 * show the caller — it only ever describes the caller's *own* token), and
 * `status` is the HTTP status the endpoint should answer with. Everything
 * that isn't a server misconfiguration is a 403: the endpoint never
 * distinguishes "your token is bad" from "you aren't an admin" with anything
 * more than this label, and never echoes Supabase's own error text back.
 */
export class AdminAuthError extends Error {
  constructor(reason, message, status = 403) {
    super(message);
    this.name = "AdminAuthError";
    this.reason = reason;
    this.status = status;
  }
}

// A Supabase access token is a compact bearer credential: printable ASCII,
// no spaces. Both bounds are generous — they exist to reject junk cheaply,
// not to second-guess Supabase's token format.
const MAX_TOKEN_LENGTH = 4096;
const PRINTABLE_ASCII_RE = /^[\x21-\x7e]+$/;

let _client = null;

/**
 * The server-side Supabase client, built from the SECRET key so it can read
 * `admins` (whose RLS only lets an authenticated user see their *own* row —
 * see db/schema.sql) and so `auth.getUser()` is answered by Supabase rather
 * than trusted from the caller.
 *
 * Session persistence is off on purpose: a serverless invocation has no
 * durable storage and no browser URL, and a cached session here would be a
 * cross-request leak between two different callers hitting a warm instance.
 */
export function getAdminClient(env = process.env) {
  if (_client) return _client;
  const url = env.SB_URL;
  const secretKey = env.SB_SEC_KEY;
  if (!url || !secretKey) {
    // 500, not 403: this is our bug, not the caller's. The message stays
    // generic — it must not name which variable is missing.
    throw new AdminAuthError(
      "server_misconfigured",
      "Admin jobs are not configured on the server.",
      500,
    );
  }
  _client = createClient(url, secretKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  return _client;
}

/** Test seam: drop the cached client so a later call rebuilds it from env. */
export function resetAdminClient() {
  _client = null;
}

/**
 * Resolve `token` to a verified admin user, or throw `AdminAuthError`.
 *
 * Rejects, in order, on: a missing/blank/non-string token; a token Supabase
 * won't resolve to a user (forged, expired, revoked, or a key rather than a
 * user JWT); a lookup failure against `admins` (fail closed — a database
 * blip must never read as "allowed"); and a real logged-in user who simply
 * isn't on the `admins` allowlist.
 *
 * `client` is injectable so the unit tests never touch the network, matching
 * the "accept an injected client" convention in src/data/db.js.
 */
export async function verifyAdmin(token, client = null) {
  if (typeof token !== "string" || token.trim() === "") {
    throw new AdminAuthError("missing_token", "No access token was supplied.");
  }
  // Shape guard before any network call: a Supabase access token is a compact
  // bearer credential with no whitespace or control characters, so anything
  // else is rejected here rather than forwarded. This keeps a stream of
  // junk POSTs from being amplified into a stream of Supabase auth requests,
  // and keeps control characters out of the Authorization header
  // supabase-js builds from this value. It deliberately does not assume any
  // internal token *structure* (no JWT segment count) — that would turn a
  // future token-format change into a lockout.
  if (token.length > MAX_TOKEN_LENGTH || !PRINTABLE_ASCII_RE.test(token)) {
    throw new AdminAuthError("invalid_token", "That access token isn't valid.");
  }

  const sb = client || getAdminClient();

  let result;
  try {
    result = await sb.auth.getUser(token);
  } catch {
    // A thrown transport error is still a refusal — never a pass.
    throw new AdminAuthError("invalid_token", "Could not verify that access token.");
  }
  const user = result?.data?.user;
  if (result?.error || !user?.id) {
    throw new AdminAuthError("invalid_token", "That access token isn't valid.");
  }

  let row;
  try {
    const lookup = await sb
      .from("admins")
      .select("user_id")
      .eq("user_id", user.id)
      .maybeSingle();
    if (lookup?.error) throw lookup.error;
    row = lookup?.data ?? null;
  } catch {
    throw new AdminAuthError("verification_failed", "Could not verify admin status.");
  }

  if (!row) {
    throw new AdminAuthError("not_admin", "This account isn't on the admin allowlist.");
  }

  return user;
}
