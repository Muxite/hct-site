// Tests for api/'s serverless functions. They live under `_tests/`, not
// beside the files they cover, because Vercel turns *every* file directly
// under `api/` into a public route — `api/trigger-job.test.js` would deploy
// as a live `/api/trigger-job.test` endpoint. Only paths containing a `/_`
// segment are excluded (see `_lib/verifyAdmin.js`'s note), so anything that
// isn't an endpoint belongs under an underscore directory. `node --test`
// discovers them here exactly as it did before.
import { test } from "node:test";
import assert from "node:assert/strict";

import { verifyAdmin, getAdminClient, resetAdminClient, AdminAuthError } from "../_lib/verifyAdmin.js";

// The gate in front of a public URL that can spend the project's CI/LLM
// budget, so these tests are written adversarially: every path that isn't an
// unambiguous "yes" must reject, and a rejection must happen *before* the
// next step is even attempted (asserted by checking the recorded calls, not
// just the thrown error).

/**
 * Stands in for a service-role supabase-js client. Records every call so a
 * test can prove, e.g., that the `admins` table was never queried for a
 * token Supabase already refused.
 */
function fakeSupabase({
  user = null,
  getUserError = null,
  getUserThrows = null,
  adminRow = null,
  adminError = null,
} = {}) {
  const calls = [];
  return {
    calls,
    auth: {
      async getUser(token) {
        calls.push(["getUser", token]);
        if (getUserThrows) throw getUserThrows;
        return { data: { user }, error: getUserError };
      },
    },
    from(table) {
      calls.push(["from", table]);
      const builder = {
        select(cols) {
          calls.push(["select", cols]);
          return builder;
        },
        eq(col, value) {
          calls.push(["eq", col, value]);
          return builder;
        },
        async maybeSingle() {
          calls.push(["maybeSingle"]);
          return { data: adminRow, error: adminError };
        },
      };
      return builder;
    },
  };
}

const ADMIN_USER = { id: "11111111-2222-3333-4444-555555555555", email: "admin@example.com" };

// --- case 1: no token ------------------------------------------------------

test("verifyAdmin rejects a missing token without calling Supabase at all", async () => {
  for (const token of [undefined, null, "", "   ", "\n\t"]) {
    const sb = fakeSupabase({ user: ADMIN_USER, adminRow: { user_id: ADMIN_USER.id } });
    const err = await verifyAdmin(token, sb).then(
      () => null,
      (e) => e,
    );
    assert.ok(err instanceof AdminAuthError, `expected a rejection for ${JSON.stringify(token)}`);
    assert.equal(err.reason, "missing_token");
    assert.equal(err.status, 403);
    assert.deepEqual(sb.calls, [], "no Supabase call may happen for a missing token");
  }
});

test("verifyAdmin rejects a non-string token (a JSON body can carry anything)", async () => {
  for (const token of [123, true, {}, [], { access_token: "x" }]) {
    const sb = fakeSupabase({ user: ADMIN_USER, adminRow: { user_id: ADMIN_USER.id } });
    const err = await verifyAdmin(token, sb).then(
      () => null,
      (e) => e,
    );
    assert.equal(err?.reason, "missing_token", `expected rejection for ${JSON.stringify(token)}`);
    assert.deepEqual(sb.calls, []);
  }
});

// --- case 2: invalid token -------------------------------------------------

test("verifyAdmin rejects a token Supabase won't resolve, and never reaches `admins`", async () => {
  const sb = fakeSupabase({ user: null, getUserError: { message: "invalid JWT" } });
  const err = await verifyAdmin("garbage.token.value", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "invalid_token");
  assert.equal(err.status, 403);
  assert.deepEqual(sb.calls, [["getUser", "garbage.token.value"]]);
  assert.equal(
    sb.calls.some((c) => c[0] === "from"),
    false,
    "the admins table must not be queried for an unverified token",
  );
});

test("verifyAdmin rejects when Supabase returns no error but also no user", async () => {
  const sb = fakeSupabase({ user: null, getUserError: null });
  const err = await verifyAdmin("expired.token", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "invalid_token");
  assert.deepEqual(sb.calls, [["getUser", "expired.token"]]);
});

test("verifyAdmin rejects when Supabase returns a user without an id", async () => {
  const sb = fakeSupabase({ user: { email: "nobody@example.com" } });
  const err = await verifyAdmin("odd.token", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "invalid_token");
});

test("verifyAdmin rejects (never passes) when the getUser call throws outright", async () => {
  const sb = fakeSupabase({ getUserThrows: new Error("network down") });
  const err = await verifyAdmin("some.token", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "invalid_token");
  assert.equal(err.status, 403);
});

test("verifyAdmin rejects a malformed token shape before it can reach Supabase", async () => {
  const malformed = [
    "has space",
    "line\nbreak",
    "carriage\r\nreturn: injected-header",
    "tab\tseparated",
    "nøn-ascii",
    "x".repeat(4097),
  ];
  for (const token of malformed) {
    const sb = fakeSupabase({ user: ADMIN_USER, adminRow: { user_id: ADMIN_USER.id } });
    const err = await verifyAdmin(token, sb).then(
      () => null,
      (e) => e,
    );
    assert.equal(err?.reason, "invalid_token", `expected rejection for ${JSON.stringify(token)}`);
    assert.deepEqual(sb.calls, [], "a malformed token must not be forwarded to Supabase");
  }
});

test("the shape guard still lets a normal JWT-shaped token through", async () => {
  // base64url uses `-` and `_`, and the segments are dot-separated — none of
  // which the guard may reject.
  const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhLWItYyJ9.s1gn-ature_value";
  const sb = fakeSupabase({ user: ADMIN_USER, adminRow: { user_id: ADMIN_USER.id } });
  const user = await verifyAdmin(jwt, sb);
  assert.equal(user.id, ADMIN_USER.id);
  assert.deepEqual(sb.calls[0], ["getUser", jwt]);
});

// --- case 3: valid session, non-admin user ---------------------------------

test("verifyAdmin rejects a real logged-in user who isn't on the admins allowlist", async () => {
  const visitor = { id: "99999999-0000-0000-0000-000000000000", email: "visitor@example.com" };
  const sb = fakeSupabase({ user: visitor, adminRow: null });
  const err = await verifyAdmin("valid.but.not.admin", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "not_admin");
  assert.equal(err.status, 403);
  assert.deepEqual(sb.calls, [
    ["getUser", "valid.but.not.admin"],
    ["from", "admins"],
    ["select", "user_id"],
    ["eq", "user_id", visitor.id],
    ["maybeSingle"],
  ]);
});

test("verifyAdmin fails closed when the admins lookup itself errors", async () => {
  const sb = fakeSupabase({ user: ADMIN_USER, adminError: { message: "connection reset" } });
  const err = await verifyAdmin("valid.token", sb).then(
    () => null,
    (e) => e,
  );
  assert.equal(err?.reason, "verification_failed");
  assert.equal(err.status, 403);
});

// --- case 4: valid admin ---------------------------------------------------

test("verifyAdmin resolves to the user for a valid token belonging to an admin", async () => {
  const sb = fakeSupabase({ user: ADMIN_USER, adminRow: { user_id: ADMIN_USER.id } });
  const user = await verifyAdmin("valid.admin.token", sb);
  assert.equal(user.id, ADMIN_USER.id);
  assert.deepEqual(sb.calls, [
    ["getUser", "valid.admin.token"],
    ["from", "admins"],
    ["select", "user_id"],
    ["eq", "user_id", ADMIN_USER.id],
    ["maybeSingle"],
  ]);
});

test("verifyAdmin looks the user up by the id Supabase returned, not one the caller supplied", async () => {
  // A caller who sends a token for user B can't make the lookup happen for
  // admin A: the id comes from getUser's answer, nowhere else.
  const sb = fakeSupabase({ user: { id: "from-supabase" }, adminRow: { user_id: "from-supabase" } });
  await verifyAdmin("token-claiming-to-be-someone-else", sb);
  assert.deepEqual(sb.calls.find((c) => c[0] === "eq"), ["eq", "user_id", "from-supabase"]);
});

// --- server client construction -------------------------------------------

test("getAdminClient refuses to build a client without SB_URL/SB_SEC_KEY", () => {
  resetAdminClient();
  for (const env of [{}, { SB_URL: "https://x.supabase.co" }, { SB_SEC_KEY: "sb_secret_x" }]) {
    const err = (() => {
      try {
        getAdminClient(env);
        return null;
      } catch (e) {
        return e;
      }
    })();
    assert.ok(err instanceof AdminAuthError);
    assert.equal(err.reason, "server_misconfigured");
    assert.equal(err.status, 500);
    assert.doesNotMatch(err.message, /SB_URL|SB_SEC_KEY/, "the message must not name the variable");
  }
});

test("getAdminClient builds and caches a client when the env is present", () => {
  resetAdminClient();
  const env = { SB_URL: "https://example.supabase.co", SB_SEC_KEY: "sb_secret_test" };
  const first = getAdminClient(env);
  assert.ok(first?.auth, "expected a supabase-js client");
  assert.equal(getAdminClient(env), first, "the client should be built once per instance");
  resetAdminClient();
});
