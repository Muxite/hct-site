import { useRef, useState } from "react";
import { assetUrl, isImageFile } from "../lib/format.js";
import "../admin.css";

/**
 * Inline image editor for a single admin-editable image field (a person's
 * photo, a project hero image, a paper figure, ...). Presentational only —
 * takes a plain `editable` boolean from whichever page renders it; it does
 * NOT import AdminContext/useAdmin() itself (see EditableText.jsx for the
 * same convention). The caller derives `editable={isAdmin && editMode}` from
 * `useAdmin()` and supplies `onSave(file)`.
 *
 * `onSave` receives the raw selected `File` and is awaited with no
 * optimistic update — uploading it (data/storage.js) and persisting the
 * resulting path/URL is the caller's job, not this component's; it has no
 * network calls of its own. Matches Feedback.jsx's submit flow: both
 * buttons disable while saving, a failure shows an inline error and leaves
 * the editor open. A picked file is also rejected client-side (same inline
 * error) unless its `type` starts with "image/" — `accept="image/*"` on the
 * `<input>` is a UI hint only and trivially bypassed.
 *
 * Read mode renders `value` through `assetUrl()` (same normalization
 * People.jsx/ProjectPage.jsx use for DB-stored asset paths) with the same
 * broken-image `onError` fallback convention, plus a trailing "Replace"
 * (or "Add image" when there's nothing to show yet) button when `editable`.
 * `fallback` and `alt` are optional since different call sites need
 * different fallback images/alt text (People.jsx's PHOTO_FALLBACK isn't
 * right for a project hero) — without them the fallback behavior couldn't
 * be shared across call sites at all.
 */
export default function EditableImage({ value, onSave, editable = false, alt = "", fallback = null }) {
  const [editing, setEditing] = useState(false);
  const [file, setFile] = useState(null);
  const [broken, setBroken] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");
  const inputRef = useRef(null);

  const src = value ? assetUrl(value) : fallback;
  const saving = status === "saving";

  function startEdit() {
    setFile(null);
    setStatus("idle");
    setErrorMsg("");
    setEditing(true);
  }

  function resetPicker() {
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  // `accept="image/*"` on the <input> below is a UI hint only (trivially
  // bypassed via an OS "All files" picker option) — `isImageFile()` is the
  // actual enforcement. Deliberately just a MIME sniff-check, not a size
  // cap: a size limit would be an invented business rule (no spec for one),
  // but "the file is actually an image" is this component's own contract,
  // regardless of size. Reuses the existing error-state UI (`status`/
  // `errorMsg`) rather than adding a second error affordance.
  function handleFileChange(e) {
    const picked = e.target.files?.[0] || null;
    if (!picked) {
      setFile(null);
      return;
    }
    if (!isImageFile(picked)) {
      setFile(null);
      setStatus("error");
      setErrorMsg(`"${picked.name}" doesn't look like an image (${picked.type || "unknown file type"})`);
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setStatus("idle");
    setErrorMsg("");
    setFile(picked);
  }

  function cancel() {
    if (saving) return; // no cancelling mid-flight, same as Feedback.jsx
    setEditing(false);
    resetPicker();
  }

  async function handleSave() {
    if (!file || saving) return;
    setStatus("saving");
    try {
      await onSave(file);
      setStatus("idle");
      setEditing(false);
      resetPicker();
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  if (!editing) {
    return (
      <span className="editable-image">
        {src && !broken ? (
          <img
            className="editable-image__img"
            alt={alt}
            src={src}
            loading="lazy"
            onError={(e) => {
              e.currentTarget.onerror = null;
              if (fallback) {
                e.currentTarget.src = fallback;
              } else {
                setBroken(true);
              }
            }}
          />
        ) : (
          editable && <span className="editable-image__placeholder">No image</span>
        )}
        {editable && (
          <button type="button" className="admin-btn" onClick={startEdit}>
            {src && !broken ? "Replace" : "Add image"}
          </button>
        )}
      </span>
    );
  }

  return (
    <span className="editable-image editable-image--editing">
      <label
        className={`admin-btn editable-image__file-label${
          saving ? " editable-image__file-label--disabled" : ""
        }`}
      >
        Choose file
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="sr-only"
          disabled={saving}
          onChange={handleFileChange}
        />
      </label>
      {file && <span className="editable-image__filename">{file.name}</span>}
      <span className="editable-image__actions">
        <button type="button" className="admin-btn" onClick={cancel} disabled={saving}>
          Cancel
        </button>
        <button
          type="button"
          className="admin-btn admin-btn--primary"
          onClick={handleSave}
          disabled={!file || saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </span>
      {status === "error" && (
        <span className="editable-image__error" role="alert">
          Couldn't save — {errorMsg}
        </span>
      )}
    </span>
  );
}
