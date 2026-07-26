import { useState } from "react";
import { useAdmin } from "../context/AdminContext.jsx";
import "../admin.css";

// /admin — auth foundation only: login/logout + admin-status detection.
// No CV upload, no exemplar UI, no content-editing wiring yet — those are
// later tasks (10/12) once this page has somewhere to hang them.
export default function AdminPage() {
  const { mock, loading, session, isAdmin, editMode, setEditMode, signIn, signOut } = useAdmin();

  if (mock) {
    return (
      <div className="admin-page">
        <h1>Admin</h1>
        <p className="state">
          This offline preview build (VITE_MOCK) has no live Supabase connection, so
          admin sign-in isn't available here.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="admin-page">
        <h1>Admin</h1>
        <p className="state">Checking session…</p>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="admin-page">
        <h1>Admin</h1>
        <LoginForm signIn={signIn} />
      </div>
    );
  }

  return (
    <div className="admin-page">
      <h1>Admin</h1>
      <p className="admin-status">
        Signed in as <strong>{session.user?.email}</strong>
        {isAdmin ? " — admin" : " — not an admin"}
      </p>

      {isAdmin ? (
        <label className="admin-toggle">
          <input
            type="checkbox"
            checked={editMode}
            onChange={(e) => setEditMode(e.target.checked)}
          />
          Edit mode
        </label>
      ) : (
        <p className="state">
          This account can sign in, but it isn't on the admin allowlist yet.
        </p>
      )}

      <button type="button" className="admin-btn" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}

// Logged-out state: email + magic link. Await-then-flip-status, no
// optimistic UI — same spirit as Feedback.jsx's submit flow.
function LoginForm({ signIn }) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | submitting | sent | error
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || status === "submitting") return;
    setStatus("submitting");
    try {
      await signIn(trimmed);
      setStatus("sent");
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  return (
    <>
      <form className="admin-login" onSubmit={handleSubmit}>
        <label htmlFor="admin-email">Email</label>
        <input
          id="admin-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          required
          disabled={status === "submitting"}
        />
        <button
          type="submit"
          className="admin-btn admin-btn--primary"
          disabled={!email.trim() || status === "submitting"}
        >
          {status === "submitting" ? "Sending…" : "Send magic link"}
        </button>
      </form>

      {status === "sent" && (
        <p className="admin-status admin-status--done">
          Check your email for a sign-in link.
        </p>
      )}
      {status === "error" && (
        <p className="admin-status admin-status--error">Couldn't send the link — {errorMsg}</p>
      )}
    </>
  );
}
