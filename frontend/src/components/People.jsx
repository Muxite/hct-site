import { useEffect, useState } from "react";
import { splitByKind, emailLabel, assetUrl, isImageFile, photoPath } from "../lib/format.js";
import { useAdmin } from "../context/AdminContext.jsx";
import { insertPerson, updatePerson, deletePerson } from "../data/db.js";
import { uploadToSiteMedia } from "../data/storage.js";
import EditableImage from "./EditableImage.jsx";
import "../admin.css";

const PHOTO_FALLBACK = "/Human Communication Technologies Lab_files/person.png";

// `photoPath` (people/<slug>.<ext>) now lives in lib/format.js — shared with
// components/SiteHome.jsx's own roster CRUD (Gallery's separate render path,
// same underlying people table) so both agree on the upload path convention.

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
    const photo = file ? await uploadToSiteMedia(file, photoPath(fields.name, file)) : null;
    const nextSortOrder = roster.reduce((max, p) => Math.max(max, p.sort_order || 0), 0) + 1;
    const payload = { ...fields, photo, sort_order: nextSortOrder };
    const created = await insertPerson(payload);
    setRoster((prev) => [...prev, created || { ...payload, bio: null }]);
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

function toDraft(person) {
  return {
    role: person.role || "",
    email: person.email || "",
    bio: person.bio || "",
    kind: person.kind || "current",
  };
}

function PersonTile({ person, editable, onSaved, onDeleted }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => toDraft(person));
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");

  const photo = person.photo ? assetUrl(person.photo) : PHOTO_FALLBACK;

  function startEdit() {
    setDraft(toDraft(person));
    setStatus("idle");
    setErrorMsg("");
    setEditing(true);
  }

  function cancel() {
    if (status === "saving") return; // no cancelling mid-flight, same as EditableText.jsx
    setEditing(false);
  }

  async function handleSave(e) {
    e.preventDefault();
    if (status === "saving") return;
    setStatus("saving");
    try {
      const fields = {
        role: draft.role.trim() || null,
        email: draft.email.trim() || null,
        bio: draft.bio.trim() || null,
        kind: draft.kind,
      };
      const saved = await updatePerson(person.name, fields);
      onSaved(saved || { ...person, ...fields });
      setStatus("idle");
      setEditing(false);
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  async function handleDelete() {
    if (status === "saving") return;
    if (!window.confirm(`Delete ${person.name}? This can't be undone.`)) return;
    setStatus("saving");
    setErrorMsg("");
    try {
      await deletePerson(person.name);
      onDeleted(person.name);
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  async function handlePhotoSave(file) {
    const url = await uploadToSiteMedia(file, photoPath(person.name, file));
    const saved = await updatePerson(person.name, { photo: url });
    onSaved(saved || { ...person, photo: url });
  }

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
                people.yaml + `hct-manager sync-content` always force-write
                `kind` from the YAML, so a status flipped here can be reverted
                (or, for an admin-added person entirely, deleted — see the
                report) by the next routine sync unless people.yaml is kept
                in sync by whoever maintains it. */}
            <p className="admin-caption">
              Status (and any other change made here) may be reverted by the next
              CV/people sync unless people.yaml is updated to match — coordinate
              with whoever maintains it.
            </p>
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

const EMPTY_ADD_FORM = { name: "", role: "", email: "", kind: "current" };

// "Add person" inline form — name/role/email/photo/status, name set once at
// creation (see decision #6 / people_name_key). `onAdd(fields, file)` does
// the actual upload + insert (People.jsx) and is awaited with no optimistic
// UI, same Save/Cancel-disable-while-saving convention as EditableText.jsx.
function AddPersonForm({ onAdd }) {
  const [fields, setFields] = useState(EMPTY_ADD_FORM);
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");

  function setField(key, value) {
    setFields((f) => ({ ...f, [key]: value }));
  }

  // `accept="image/*"` below is a UI hint only (trivially bypassed, e.g. an
  // OS "All files" picker option) — same enforcement EditableImage.jsx uses
  // for the same reason, reused here since this form's photo field is a
  // plain <input type="file"> rather than an <EditableImage> (there's no
  // existing person/value to edit yet).
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
      e.target.value = "";
      return;
    }
    setStatus("idle");
    setErrorMsg("");
    setFile(picked);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const name = fields.name.trim();
    if (!name || status === "saving") return;
    setStatus("saving");
    try {
      await onAdd(
        {
          name,
          role: fields.role.trim() || null,
          email: fields.email.trim() || null,
          kind: fields.kind,
        },
        file,
      );
      setFields(EMPTY_ADD_FORM);
      setFile(null);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

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
      <label>
        Photo
        <input type="file" accept="image/*" onChange={handleFileChange} disabled={saving} />
      </label>
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
      <p className="admin-caption">
        Name can't be changed later — delete and re-add to fix a typo. This person
        also only lives in Supabase, not in people.yaml, so a routine CV/people
        sync will delete them again unless someone adds them there too.
      </p>
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
