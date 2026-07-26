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

const AdminContext = createContext(null);

export function AdminProvider({ children }) {
  // `loading` covers the initial getSession() round trip so AdminPage can
  // show a neutral "checking…" state instead of flashing "logged out" first.
  // A mock build never has a session to check, so it starts already settled.
  // Same for an admin-preview build: isAdmin/editMode boot already forced
  // true and no session check ever runs (see the effect below).
  const [session, setSession] = useState(null);
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
