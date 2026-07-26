import { useEffect, useState } from "react";
import { splitByKind, emailLabel, assetUrl } from "../lib/format.js";
import { useAdmin } from "../context/AdminContext.jsx";
import {
  PEOPLE_KIND_SYNC_CAVEAT,
  ADD_PERSON_SYNC_CAVEAT,
  addPersonWithPhoto,
  usePersonEditor,
  useAddPersonForm,
} from "../hooks/usePersonEditor.js";
import EditableImage from "./EditableImage.jsx";
import "../admin.css";

const PHOTO_FALLBACK = "/Human Communication Technologies Lab_files/person.png";

// The edit/delete/photo state machine, the add-form state machine, the
// field validation, the `photoPath`/sort_order logic, and the people.kind
// sync caveat text all now live in hooks/usePersonEditor.js — shared with
// components/SiteHome.jsx's own roster CRUD (Gallery's separate render
// path, same underlying people table) so neither copy can silently drift
// from the other. This file only owns the Classic `.person-tile` markup.

// Lab roster, original layout: current members as round-photo tiles, alumni
// grouped beneath under a "year"-style heading. When `isAdmin && editMode`
// (see AdminContext.jsx), each tile grows edit/remove affordances and an
// "Add person" form appears beneath the roster — see PersonTile/AddPersonForm.
export default function People({ people }) {
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;

  // Local copy so a successful add/edit/delete can update the roster in
  // place without a full Home.jsx refetch; kept in sync if the `people` prop
  // itself ever changes (e.g. Home.jsx refetching on navigation).
  const [roster, setRoster] = useState(people || []);
  useEffect(() => {
    setRoster(people || []);
  }, [people]);

  const [current, alumni] = splitByKind(roster, "alumni");

  function handleSaved(next) {
    setRoster((prev) => prev.map((p) => (p.name === next.name ? { ...p, ...next } : p)));
  }

  function handleDeleted(name) {
    setRoster((prev) => prev.filter((p) => p.name !== name));
  }

  async function handleAdd(fields, file) {
    const created = await addPersonWithPhoto(fields, file, roster);
    setRoster((prev) => [...prev, created]);
  }

  if (!current.length && !alumni.length && !editable) {
    return <p className="state">Roster coming soon.</p>;
  }

  return (
    <>
      {(current.length > 0 || editable) && (
        <div className="wrapper" id="people">
          {current.map((p) => (
            <PersonTile
              key={p.name}
              person={p}
              editable={editable}
              onSaved={handleSaved}
              onDeleted={handleDeleted}
            />
          ))}
        </div>
      )}
      {alumni.length > 0 && (
        <>
          <h3 className="year">Alumni</h3>
          <div className="wrapper" id="alumni">
            {alumni.map((p) => (
              <PersonTile
                key={p.name}
                person={p}
                editable={editable}
                onSaved={handleSaved}
                onDeleted={handleDeleted}
              />
            ))}
          </div>
        </>
      )}
      {editable && <AddPersonForm onAdd={handleAdd} />}
    </>
  );
}

function PersonTile({ person, editable, onSaved, onDeleted }) {
  const {
    editing,
    draft,
    setDraft,
    status,
    errorMsg,
    startEdit,
    cancel,
    handleSave,
    handleDelete,
    handlePhotoSave,
  } = usePersonEditor(person, { onSaved, onDeleted });

  const photo = person.photo ? assetUrl(person.photo) : PHOTO_FALLBACK;

  return (
    <div className="person-tile">
      <div className="photo">
        {editable ? (
          <EditableImage
            value={person.photo}
            onSave={handlePhotoSave}
            editable={editable}
            alt={person.name}
            fallback={PHOTO_FALLBACK}
          />
        ) : (
          <img
            alt={person.name}
            src={photo}
            loading="lazy"
            onError={(e) => {
              e.currentTarget.onerror = null;
              e.currentTarget.src = PHOTO_FALLBACK;
            }}
          />
        )}
      </div>
      <div className="info">
        {/* `name` is set once at creation and is not editable here — see
            db/schema.sql's people_name_key and db.js's insertPerson/updatePerson
            comments; delete + recreate is the documented fix for a typo. */}
        <strong>{person.name}</strong>

        {!editing ? (
          <>
            {person.role && (
              <div className="project" style={{ whiteSpace: "nowrap" }}>
                {person.role}
              </div>
            )}
            {person.email && (
              <div className="email">
                <a href={`mailto:${person.email}`}>{emailLabel(person.email)}</a>
              </div>
            )}
            {editable && (
              <div className="admin-person-actions">
                <button type="button" className="admin-btn" onClick={startEdit}>
                  Edit
                </button>
                <button
                  type="button"
                  className="admin-btn"
                  onClick={handleDelete}
                  disabled={status === "saving"}
                >
                  {status === "saving" ? "Removing…" : "Remove"}
                </button>
              </div>
            )}
            {/* Shared error slot for both the Edit-save flow and the Remove
                flow (e.g. the project_people delete-guard message) — the
                thrown message is already a complete sentence either way, so
                this doesn't prefix it with an action-specific label. */}
            {status === "error" && (
              <p className="editable-text__error" role="alert">
                {errorMsg}
              </p>
            )}
          </>
        ) : (
          <form className="admin-person-form" onSubmit={handleSave}>
            <label>
              Role
              <input
                type="text"
                value={draft.role}
                onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={draft.email}
                onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Bio
              <textarea
                rows={3}
                value={draft.bio}
                onChange={(e) => setDraft((d) => ({ ...d, bio: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Status
              <select
                value={draft.kind}
                onChange={(e) => setDraft((d) => ({ ...d, kind: e.target.value }))}
                disabled={status === "saving"}
              >
                <option value="current">Current</option>
                <option value="alumni">Alumni</option>
              </select>
            </label>
            {/* people.kind decision (Task 7 / plan addendum): built anyway,
                documented here — see task-7-report.md for the full reasoning.
                Caveat text now lives once in hooks/usePersonEditor.js, shared
                with SiteHome.jsx's own edit form. */}
            <p className="admin-caption">{PEOPLE_KIND_SYNC_CAVEAT}</p>
            <div className="editable-text__actions">
              <button
                type="button"
                className="admin-btn"
                onClick={cancel}
                disabled={status === "saving"}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn--primary"
                disabled={status === "saving"}
              >
                {status === "saving" ? "Saving…" : "Save"}
              </button>
            </div>
            {status === "error" && (
              <p className="editable-text__error" role="alert">
                Couldn't save — {errorMsg}
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}

// "Add person" inline form — name/role/email/photo/status, name set once at
// creation (see decision #6 / people_name_key). `onAdd(fields, file)` does
// the actual upload + insert (People.jsx) and is awaited with no optimistic
// UI, same Save/Cancel-disable-while-saving convention as EditableText.jsx.
function AddPersonForm({ onAdd }) {
  const { fields, setField, file, status, errorMsg, handleFileChange, handleSubmit } = useAddPersonForm(onAdd);
  const saving = status === "saving";

  return (
    <form className="admin-person-form admin-add-person" onSubmit={handleSubmit}>
      <h4>Add person</h4>
      <label>
        Name
        <input
          type="text"
          value={fields.name}
          onChange={(e) => setField("name", e.target.value)}
          required
          disabled={saving}
        />
      </label>
      <label>
        Role
        <input
          type="text"
          value={fields.role}
          onChange={(e) => setField("role", e.target.value)}
          disabled={saving}
        />
      </label>
      <label>
        Email
        <input
          type="email"
          value={fields.email}
          onChange={(e) => setField("email", e.target.value)}
          disabled={saving}
        />
      </label>
      <label htmlFor="add-person-photo">Photo</label>
      {/* `accept="image/*"` below is a UI hint only (trivially bypassed,
          e.g. an OS "All files" picker option) — useAddPersonForm's
          handleFileChange is the actual enforcement. Hidden behind a styled
          label like every other file picker in the app (EditableImage.jsx,
          AdminPage.jsx's CV upload) instead of the bare native control. */}
      <label className={`admin-btn${saving ? " admin-btn--disabled" : ""}`}>
        Choose file
        <input
          id="add-person-photo"
          type="file"
          accept="image/*"
          className="sr-only"
          onChange={handleFileChange}
          disabled={saving}
        />
      </label>
      {file && <span className="editable-image__filename">{file.name}</span>}
      <label>
        Status
        <select
          value={fields.kind}
          onChange={(e) => setField("kind", e.target.value)}
          disabled={saving}
        >
          <option value="current">Current</option>
          <option value="alumni">Alumni</option>
        </select>
      </label>
      <p className="admin-caption">{ADD_PERSON_SYNC_CAVEAT}</p>
      <div className="editable-text__actions">
        <button
          type="submit"
          className="admin-btn admin-btn--primary"
          disabled={!fields.name.trim() || saving}
        >
          {saving ? "Adding…" : "Add person"}
        </button>
      </div>
      {status === "error" && (
        <p className="editable-text__error" role="alert">
          Couldn't add — {errorMsg}
        </p>
      )}
    </form>
  );
}
