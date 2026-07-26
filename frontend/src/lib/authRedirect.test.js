import { test } from "node:test";
import assert from "node:assert/strict";

import { adminRedirectUrl } from "./authRedirect.js";
import { pathFromHash } from "./router.js";

/**
 * `parseParametersFromURL` as @supabase/auth-js actually implements it
 * (node_modules/@supabase/auth-js/dist/module/lib/helpers.js, v2.108.0):
 * fragment params first, then search params, with search taking precedence.
 *
 * Reproduced here rather than imported because it isn't part of the package's
 * public API. The point of the tests below isn't to test the library — it's to
 * pin the interaction between *our* redirect URL and that parser, which is
 * what the implicit/PKCE choice turns on and what silently broke sign-in once
 * already.
 */
function parseParametersFromURL(href) {
  const result = {};
  const url = new URL(href);
  if (url.hash && url.hash[0] === "#") {
    try {
      new URLSearchParams(url.hash.substring(1)).forEach((v, k) => (result[k] = v));
    } catch {
      /* hash is not a query string */
    }
  }
  url.searchParams.forEach((v, k) => (result[k] = v));
  return result;
}

test("adminRedirectUrl points at the app's own #/admin route", () => {
  assert.equal(
    adminRedirectUrl({ origin: "https://hct.example", pathname: "/" }),
    "https://hct.example/#/admin",
  );
});

test("adminRedirectUrl keeps a sub-path deploy's base path", () => {
  assert.equal(
    adminRedirectUrl({ origin: "https://x.github.io", pathname: "/hct-site/" }),
    "https://x.github.io/hct-site/#/admin",
  );
});

test("a PKCE callback to that URL parses: supabase-js sees the code, the router sees /admin", () => {
  // PKCE returns the code as a query param, so it lands beside the fragment
  // rather than inside it. Both readers get what they need.
  const landed = "https://hct.example/?code=abc123#/admin";
  assert.equal(parseParametersFromURL(landed).code, "abc123");
  assert.equal(pathFromHash(new URL(landed).hash), "/admin");
});

test("the same URL under the implicit flow loses the session entirely", () => {
  // Why data/db.js pins flowType: 'pkce'. The implicit flow appends its tokens
  // to the fragment, which already holds "/admin" — the parser then reads the
  // first key as the literal "/admin#access_token", so `access_token` is
  // undefined, auth-js's implicit-grant check fails, and no session is made.
  // This asserts the broken behaviour on purpose: if a future supabase-js ever
  // handles it, this test failing is the signal to revisit the note in db.js.
  const landed = "https://hct.example/#/admin#access_token=abc&refresh_token=r&type=magiclink";
  const params = parseParametersFromURL(landed);
  assert.equal(params.access_token, undefined);
  assert.equal(params["/admin#access_token"], "abc");
});
