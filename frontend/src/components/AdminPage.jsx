import { useEffect, useState } from "react";
import { useAdmin } from "../context/AdminContext.jsx";
import { uploadToCvUploads } from "../data/storage.js";
import { useJobRunner, runLabel } from "../data/jobs.js";
import { getStyleProfile, updateStyleProfileExcerpt } from "../data/db.js";
import { isDocxFile } from "../lib/format.js";
import "../admin.css";

// /admin — login/logout + admin-status detection, plus the CV upload and its
// "Sync now" CI trigger, and the writing-voice exemplar + style-regen trigger.
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
          <StyleProfileSection accessToken={session.access_token} />
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

// Writing-voice exemplar + regenerate trigger. The textarea is a direct
// authenticated write to `style_profile.source_excerpt` (updateStyleProfileExcerpt
// — no CI involved, same as EditableText's plain Supabase writes); "Regenerate
// style guide" asks CI to run `hct-manager style-regen`, which distills the
// saved excerpt into `style_profile.profile_text` via `src/style.py`'s
// analyze_style() (same job plumbing as CvSyncSection above, job type
// "style-regen"). `profile_text` then feeds into describe.py/summarize.py as a
// distinct `voice_profile` block, kept separate from summarize.py's own
// audience-style (A/B/C/D/E) parameter — see backend/src/summarize.py.
//
// `EXCERPT_MAX` mirrors db/schema.sql's `style_profile_source_excerpt_check`.
// The DB constraint is the real bound (a direct API write bypasses this
// entirely); the textarea's `maxLength` just means a long paste is trimmed
// with a visible counter instead of failing at save time with a raw Postgres
// constraint error. Keep the two numbers in step.
const EXCERPT_MAX = 20000;

function StyleProfileSection({ accessToken }) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [profileText, setProfileText] = useState("");
  const [saveStatus, setSaveStatus] = useState("idle"); // idle | saving | saved | error
  const [saveError, setSaveError] = useState("");
  const { phase, run, error, start } = useJobRunner(accessToken);

  const saving = saveStatus === "saving";
  const busy = saving || phase === "triggering" || phase === "queued" || phase === "running";

  useEffect(() => {
    let alive = true;
    getStyleProfile()
      .then((row) => {
        if (!alive) return;
        setExcerpt(row?.source_excerpt || "");
        setProfileText(row?.profile_text || "");
      })
      .catch((err) => {
        if (alive) setLoadError(String(err?.message || err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // Once a style-regen run completes, pull the freshly written profile_text
  // back in — it was generated server-side, so nothing else refreshes it.
  useEffect(() => {
    if (phase !== "done") return;
    let alive = true;
    getStyleProfile()
      .then((row) => {
        if (alive) setProfileText(row?.profile_text || "");
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [phase]);

  // Returns whether the save landed, so handleRegenerate below can bail
  // before triggering the job on a failed save (mirrors CvSyncSection's
  // handleSync, which only calls start("cv-sync") once the upload succeeds).
  async function handleSave() {
    if (saveStatus === "saving") return false;
    setSaveStatus("saving");
    setSaveError("");
    try {
      await updateStyleProfileExcerpt(excerpt);
      setSaveStatus("saved");
      return true;
    } catch (err) {
      setSaveStatus("error");
      setSaveError(String(err?.message || err));
      return false;
    }
  }

  // Save whatever's currently in the textarea, then trigger style-regen —
  // deliberately in this order and never in parallel, same reasoning as
  // CvSyncSection.handleSync above: style-regen reads Supabase's
  // style_profile.source_excerpt straight off the row, so triggering it
  // without saving first would regenerate from whatever excerpt was last
  // saved, silently ignoring any edit still sitting in the textarea.
  async function handleRegenerate() {
    if (busy || !excerpt.trim()) return;
    const saved = await handleSave();
    if (!saved) return;
    await start("style-regen");
  }

  if (loading) {
    return (
      <section className="admin-style">
        <h2 className="admin-style__heading">Writing voice</h2>
        <p className="state">Loading…</p>
      </section>
    );
  }

  const statusText = runLabel(phase, run);

  return (
    <section className="admin-style">
      <h2 className="admin-style__heading">Writing voice</h2>
      <p className="admin-caption">
        Paste text that sounds like the lab (a paper description, an email, a bio),
        save it, then regenerate the style guide the AI matches when writing
        descriptions and summaries.
      </p>

      {loadError && (
        <p className="admin-status admin-status--error" role="alert">
          Couldn't load the saved exemplar — {loadError}
        </p>
      )}

      <textarea
        className="admin-style__textarea"
        value={excerpt}
        onChange={(e) => {
          setExcerpt(e.target.value);
          setSaveStatus("idle");
        }}
        placeholder="Paste an example of the lab's writing here…"
        rows={8}
        maxLength={EXCERPT_MAX}
      />

      {excerpt.length > EXCERPT_MAX * 0.9 && (
        <p className="admin-caption">
          {excerpt.length.toLocaleString()} / {EXCERPT_MAX.toLocaleString()} characters
          {excerpt.length >= EXCERPT_MAX
            ? " — at the limit; anything further is trimmed. A voice sample only needs a few paragraphs."
            : "."}
        </p>
      )}

      <div className="admin-style__controls">
        <button
          type="button"
          className="admin-btn admin-btn--primary"
          onClick={handleSave}
          disabled={busy}
        >
          {saving ? "Saving…" : "Save exemplar"}
        </button>
        <button
          type="button"
          className="admin-btn"
          onClick={handleRegenerate}
          disabled={busy || !excerpt.trim()}
        >
          {busy ? "Working…" : "Regenerate style guide"}
        </button>
      </div>

      {saveStatus === "saved" && (
        <p className="admin-status admin-status--done">Saved.</p>
      )}
      {saveStatus === "error" && (
        <p className="admin-status admin-status--error" role="alert">
          Couldn't save — {saveError}
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

      <h3 className="admin-style__subheading">Current style guide</h3>
      {profileText ? (
        <pre className="admin-style__profile">{profileText}</pre>
      ) : (
        <p className="admin-caption">
          Not generated yet — save an exemplar above, then regenerate.
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
