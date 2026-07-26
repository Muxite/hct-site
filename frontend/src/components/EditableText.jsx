import { useState } from "react";
import "../admin.css";

/**
 * Inline text editor for a single admin-editable string field (site prose,
 * a person's bio/role, a project tagline, ...). Presentational only — takes
 * a plain `editable` boolean from whichever page renders it; it does NOT
 * import AdminContext/useAdmin() itself, so it stays testable/reusable like
 * this codebase's pure helpers (lib/format.js). The caller derives
 * `editable={isAdmin && editMode}` from `useAdmin()` and supplies `onSave`.
 *
 * `onSave(nextValue)` is awaited with no optimistic update — matches
 * Feedback.jsx's submit flow: both buttons disable while saving, a failure
 * shows an inline error and leaves the editor open (the caller's `onSave`
 * does the actual Supabase write; this component has no network calls of
 * its own).
 *
 * Read mode renders `render ? render(value) : value` plus a trailing "Edit"
 * button when `editable`. Edit mode swaps in a single-line input (or a
 * textarea when `multiline`) with Save/Cancel.
 */
export default function EditableText({
  value,
  onSave,
  editable = false,
  render,
  multiline = false,
  placeholder = "",
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");

  function startEdit() {
    setDraft(value ?? "");
    setStatus("idle");
    setErrorMsg("");
    setEditing(true);
  }

  function cancel() {
    if (status === "saving") return; // no cancelling mid-flight, same as Feedback.jsx
    setEditing(false);
  }

  async function handleSave() {
    if (status === "saving") return;
    setStatus("saving");
    try {
      await onSave(draft);
      setStatus("idle");
      setEditing(false);
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  if (!editing) {
    return (
      <span className="editable-text">
        {render ? render(value) : value}
        {editable && (
          <button type="button" className="admin-btn" onClick={startEdit}>
            Edit
          </button>
        )}
      </span>
    );
  }

  const saving = status === "saving";

  return (
    <span className="editable-text editable-text--editing">
      {multiline ? (
        <textarea
          className="editable-text__field"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          disabled={saving}
          rows={4}
          autoFocus
        />
      ) : (
        <input
          type="text"
          className="editable-text__field"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          disabled={saving}
          autoFocus
        />
      )}
      <span className="editable-text__actions">
        <button type="button" className="admin-btn" onClick={cancel} disabled={saving}>
          Cancel
        </button>
        <button
          type="button"
          className="admin-btn admin-btn--primary"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </span>
      {status === "error" && (
        <span className="editable-text__error" role="alert">
          Couldn't save — {errorMsg}
        </span>
      )}
    </span>
  );
}
