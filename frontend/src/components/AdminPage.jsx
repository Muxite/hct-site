import { useState } from "react";
import { useAdmin } from "../context/AdminContext.jsx";
import { uploadToCvUploads } from "../data/storage.js";
import { useJobRunner, runLabel } from "../data/jobs.js";
import { isDocxFile } from "../lib/format.js";
import "../admin.css";

// /admin — login/logout + admin-status detection, plus the CV upload and its
// "Sync now" CI trigger. The exemplar/style-calibration UI is a later task;
// it reuses the same job plumbing with job type "style-regen".
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
        <>
          <label className="admin-toggle">
            <input
              type="checkbox"
              checked={editMode}
              onChange={(e) => setEditMode(e.target.checked)}
            />
            Edit mode
          </label>
          <CvSyncSection accessToken={session.access_token} />
        </>
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

// Upload a new CV, then ask CI to re-run the pipeline against it.
//
// Two steps, deliberately in this order and never in parallel: the docx goes
// into the private `cv-uploads` bucket at the fixed `cv/current.docx` path
// (data/storage.js), and only once that upload has actually landed does
// `cv-sync` start — the CI job's first step (`hct-manager fetch-cv`)
// downloads exactly that object, so triggering early would re-run the
// pipeline against the *previous* CV.
//
// Both the upload and the trigger are admin-gated server-side (Storage RLS
// on the bucket; api/_lib/verifyAdmin.js on the endpoint), so nothing here
// is load-bearing for security — it's a progress display.
function CvSyncSection({ accessToken }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const { phase, run, error, start } = useJobRunner(accessToken);

  const busy = uploading || phase === "triggering" || phase === "queued" || phase === "running";

  function handleFileChange(e) {
    const picked = e.target.files?.[0] || null;
    setUploadError("");
    if (picked && !isDocxFile(picked)) {
      setFile(null);
      setUploadError("The CV has to be a Word .docx file.");
      return;
    }
    setFile(picked);
  }

  async function handleSync() {
    if (!file || busy) return;
    setUploadError("");
    setUploading(true);
    try {
      await uploadToCvUploads(file);
    } catch (err) {
      setUploadError(String(err?.message || err));
      setUploading(false);
      return;
    }
    setUploading(false);
    await start("cv-sync");
  }

  const statusText = uploading ? "Uploading the CV…" : runLabel(phase, run);

  return (
    <section className="admin-cv">
      <h2 className="admin-cv__heading">CV sync</h2>
      <p className="admin-caption">
        Upload the lab's CV (.docx) and re-run the publication pipeline against it.
        Existing entries are only filled in, never overwritten.
      </p>

      <div className="admin-cv__controls">
        <label className={`admin-btn${busy ? " admin-btn--disabled" : ""}`}>
          Choose file
          <input
            type="file"
            accept=".docx"
            className="sr-only"
            disabled={busy}
            onChange={handleFileChange}
          />
        </label>
        <button
          type="button"
          className="admin-btn admin-btn--primary"
          onClick={handleSync}
          disabled={!file || busy}
        >
          {busy ? "Working…" : "Upload & sync now"}
        </button>
      </div>

      {file && <p className="admin-cv__filename">{file.name}</p>}

      {uploadError && (
        <p className="admin-status admin-status--error" role="alert">
          Couldn't upload — {uploadError}
        </p>
      )}

      {statusText && (
        <p
          className={`admin-status${
            phase === "done" ? " admin-status--done" : ""
          }${phase === "failed" ? " admin-status--error" : ""}`}
          role="status"
        >
          {statusText}
          {run?.html_url && (
            <>
              {" "}
              <a href={run.html_url} target="_blank" rel="noreferrer">
                View the run
              </a>
            </>
          )}
        </p>
      )}

      {phase === "error" && error && (
        <p className="admin-status admin-status--error" role="alert">
          Couldn't start the job — {error}
        </p>
      )}
    </section>
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
