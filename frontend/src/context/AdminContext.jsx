/**
 * Admin auth foundation — session detection, `admins`-table status, and an
 * `editMode` flag. Login/logout UI lives in components/AdminPage.jsx; content
 * editing itself is a later task (`editMode` is just a flag other components
 * will read from once that lands).
 *
 * Reuses the single Supabase client singleton from data/db.js (never builds
 * a second `GoTrueClient`) and must no-op entirely under `VITE_MOCK` — the
 * mock client (data/mockClient.js) has no `.auth` at all, so every
 * `client.auth.*` call below is gated on `isMockMode()` first.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { getClient, getAdminStatus, isMockMode } from "../data/db.js";
import { adminRedirectUrl } from "../lib/authRedirect.js";
import { shouldForceAdminPreview } from "../lib/adminPreview.js";

const MOCK = isMockMode();

// Dev-only screenshot/QA override — see lib/adminPreview.js for the guard
// itself and .env.example for how to set VITE_ADMIN_PREVIEW. Computed once
// at module load, same as MOCK above: import.meta.env values are build-time
// constants, not something that can change while the app is running.
const ADMIN_PREVIEW = shouldForceAdminPreview({
  envFlag: import.meta.env.VITE_ADMIN_PREVIEW,
  isDev: import.meta.env.DEV,
});

// Fabricated stand-in for a real Supabase Auth session — gated on the exact
// same ADMIN_PREVIEW guard as isAdmin/editMode above (not new architecture,
// just one more thing that guard controls). Without this, AdminPage.jsx's
// own `if (!session) return <LoginForm/>` branch would still show the login
// form under preview mode: everywhere else reads only `isAdmin`/`editMode`
// off this context, but AdminPage.jsx additionally checks `session` directly
// (for `session.user?.email` and the CV-sync/style-profile accessToken), and
// this flag exists specifically to unblock screenshotting that signed-in
// view, not just the isAdmin && editMode pencils elsewhere.
//
// `access_token: null` is deliberate, not an oversight: it is not a real JWT
// and never will be one. CvSyncSection/StyleProfileSection (AdminPage.jsx)
// pass `session.access_token` straight through to real backend endpoints —
// `uploadToCvUploads` (data/storage.js), the job-trigger flow
// (`useJobRunner`/`triggerJob` in data/jobs.js), and
// `updateStyleProfileExcerpt` (data/db.js). Under preview mode those calls
// will fail against the real Vercel/Supabase endpoints if actually clicked —
// there's no account behind a null token for them to authenticate as. That's
// expected and fine for a screenshot-only pass: the page still renders
// correctly (every control, label, and layout visible); actually invoking
// the CV upload or style regen isn't the point of preview mode and was never
// claimed to work here.
const PREVIEW_SESSION = ADMIN_PREVIEW
  ? { user: { email: "preview@admin.local" }, access_token: null }
  : null;

const AdminContext = createContext(null);

export function AdminProvider({ children }) {
  // `loading` covers the initial getSession() round trip so AdminPage can
  // show a neutral "checking…" state instead of flashing "logged out" first.
  // A mock build never has a session to check, so it starts already settled.
  // Same for an admin-preview build: isAdmin/editMode/session boot already
  // forced (session to the fabricated PREVIEW_SESSION above) and no session
  // check ever runs (see the effect below).
  const [session, setSession] = useState(PREVIEW_SESSION);
  const [isAdmin, setIsAdmin] = useState(ADMIN_PREVIEW);
  const [loading, setLoading] = useState(!MOCK && !ADMIN_PREVIEW);
  const [editMode, setEditMode] = useState(ADMIN_PREVIEW); // never persisted — always boots false, except under the preview override

  useEffect(() => {
    // Offline preview build: no real auth backend to check. Admin-preview
    // build: isAdmin/editMode are already forced true above, and this
    // deliberately skips getSession()/getAdminStatus() entirely — the
    // override never touches (or depends on) a real Supabase Auth session.
    if (MOCK || ADMIN_PREVIEW) return;

    let alive = true;
    const client = getClient();

    async function applySession(nextSession) {
      if (!alive) return;
      setSession(nextSession);
      if (!nextSession?.user) {
        setIsAdmin(false);
        setEditMode(false);
        setLoading(false);
        return;
      }
      try {
        const admin = await getAdminStatus(nextSession.user.id, client);
        if (alive) setIsAdmin(admin);
      } catch {
        // A denied/failed admins lookup just means "not an admin", not a
        // reason to break the rest of the page.
        if (alive) setIsAdmin(false);
      }
      if (alive) setLoading(false);
    }

    client.auth.getSession().then(({ data }) => applySession(data.session));

    const { data: subscription } = client.auth.onAuthStateChange((_event, nextSession) => {
      applySession(nextSession);
    });

    return () => {
      alive = false;
      subscription?.subscription?.unsubscribe();
    };
  }, []);

  async function signIn(email) {
    if (MOCK) throw new Error("Sign-in isn't available in this offline preview build.");
    const { error } = await getClient().auth.signInWithOtp({
      email,
      options: {
        // Supabase defaults to `shouldCreateUser: true`, which would make this
        // form an open endpoint: anyone could type any address and have
        // Supabase send them a real email and create a junk `auth.users` row
        // (an email-relay / quota-drain vector, even though RLS means such a
        // user could never actually be an admin). The lab's single admin
        // account is seeded by hand, so sign-in never needs to create one.
        shouldCreateUser: false,
        // Without this the magic link lands on the site root, which renders
        // the chromeless homepage — the admin would have to know to type
        // #/admin back in by hand. The URL's exact shape matters (it has to
        // survive supabase-js's callback parser, which is only true under the
        // PKCE flow data/db.js pins): see lib/authRedirect.js and its test.
        // Must also be listed under Supabase Auth's redirect-URL allowlist.
        emailRedirectTo: adminRedirectUrl(window.location),
      },
    });
    if (error) throw error;
  }

  async function signOut() {
    if (MOCK) return;
    // Under preview mode `session` is the fabricated PREVIEW_SESSION above,
    // so AdminPage.jsx's "Sign out" button is reachable even though nothing
    // here ever signed in for real. Guard it the same way MOCK is guarded
    // just above: a real `getClient().auth.signOut()` call would be a
    // pointless network round trip against an account that was never
    // authenticated, and `setEditMode(false)` would otherwise silently flip
    // the very override this page exists to demonstrate.
    if (ADMIN_PREVIEW) return;
    await getClient().auth.signOut();
    setEditMode(false);
  }

  const value = {
    mock: MOCK,
    adminPreview: ADMIN_PREVIEW,
    loading,
    session,
    user: session?.user ?? null,
    isAdmin,
    editMode,
    setEditMode,
    signIn,
    signOut,
  };

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

/** Read the current admin/session state. Must be called under `<AdminProvider>`. */
export function useAdmin() {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin() must be called within an <AdminProvider>");
  return ctx;
}
