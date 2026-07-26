/**
 * Shared behavioral core for the roster's inline person editor. Both
 * components/People.jsx (Classic's `.person-tile` cards) and
 * components/SiteHome.jsx's `PersonCard`/`Roster` (Gallery's `.vlab-person`
 * cards) write to the exact same `people` row via the exact same
 * insertPerson/updatePerson/deletePerson/uploadToSiteMedia calls, the same
 * field set (role/email/bio/kind), and the same `people.kind` sync-revert
 * caveat — but render two genuinely different card designs, so neither can
 * just render the other's component wholesale (see task-8-report.md).
 *
 * Before this file existed, both components independently carried their own
 * copy of the idle/saving/error state machine, the field trim/null-coalesce
 * logic, the image-type validation, and — worst of all — the caveat's exact
 * wording as a literal string in two places. That's a real drift risk: a
 * future change to any of these would have to be remembered in both files by
 * hand. This module is the one place that behavior lives now; each caller
 * still owns its own JSX/markup and its own "how do I fold the result back
 * into my local list" callback (`onSaved`/`onDeleted`, or `onAdd`).
 */
import { useState } from "react";
import { insertPerson, updatePerson, deletePerson } from "../data/db.js";
import { uploadToSiteMedia } from "../data/storage.js";
import { photoPath, isImageFile } from "../lib/format.js";

/**
 * Shown on every roster tile's edit form. `people.yaml` + `hct-manager
 * sync-content` force-write every `people` column *except*
 * role/email/photo/bio (`backend/src/sync_content.py`'s
 * `_PEOPLE_FILL_FIELDS`) — `kind` is not in that set, so a status flip made
 * here can be reverted by the next routine sync unless people.yaml is kept
 * in sync too.
 */
export const PEOPLE_KIND_SYNC_CAVEAT =
  "Status (and any other change made here) may be reverted by the next " +
  "CV/people sync unless people.yaml is updated to match — coordinate " +
  "with whoever maintains it.";

/**
 * Shown on every roster's "Add person" form. A person added this way only
 * lives in Supabase, never in people.yaml (this frontend has no way to touch
 * that file) — `_sync_people`'s `delete_stale=False` means a routine sync
 * won't delete them for that reason alone, but nothing here writes them into
 * people.yaml either, so whoever maintains it should add them there too.
 */
export const ADD_PERSON_SYNC_CAVEAT =
  "Name can't be changed later — delete and re-add to fix a typo. This person " +
  "also only lives in Supabase, not in people.yaml, so a routine CV/people " +
  "sync will delete them again unless someone adds them there too.";

/**
 * `draft` (the edit form's raw string fields) -> the payload `updatePerson`
 * writes. Blank strings null-coalesce to `null` so clearing a field in the
 * UI actually clears the column rather than writing an empty string.
 */
export function personFieldsFromDraft(draft) {
  return {
    role: draft.role.trim() || null,
    email: draft.email.trim() || null,
    bio: draft.bio.trim() || null,
    kind: draft.kind,
  };
}

function toPersonDraft(person) {
  return {
    role: person.role || "",
    email: person.email || "",
    bio: person.bio || "",
    kind: person.kind || "current",
  };
}

/**
 * The next `sort_order` for a newly-added row: one past the current max (or
 * 1 for an empty roster), so a new add lands at the end of the roster
 * instead of sorting to the top.
 */
export function nextSortOrder(items) {
  return (items || []).reduce((max, p) => Math.max(max, p.sort_order || 0), 0) + 1;
}

/**
 * Upload the optional photo, compute the next sort_order, and insert the new
 * person row — the exact sequence both People.jsx's and SiteHome.jsx's own
 * "Add person" handlers ran independently before this was extracted.
 * `insert`/`upload` are injectable (defaulting to the real db.js/storage.js
 * calls) purely so this is unit-testable without a network — same
 * "accept an injected dependency" convention data/db.js's own
 * `client = getClient()` parameters use.
 */
export async function addPersonWithPhoto(
  fields,
  file,
  existingPeople,
  { insert = insertPerson, upload = uploadToSiteMedia } = {},
) {
  const photo = file ? await upload(file, photoPath(fields.name, file)) : null;
  const payload = { ...fields, photo, sort_order: nextSortOrder(existingPeople) };
  const created = await insert(payload);
  return created || { ...payload, bio: null };
}

/**
 * One roster tile's inline edit/delete/photo-replace flow.
 * `onSaved(person)`/`onDeleted(name)` are the caller's own local-state
 * fold-in (People.jsx's `roster` state vs. SiteHome.jsx's `data.people` via
 * `onDataChange`) — this hook only owns the editing UI's state machine and
 * the actual writes, not how the result is stored afterwards.
 */
export function usePersonEditor(person, { onSaved, onDeleted }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => toPersonDraft(person));
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");

  function startEdit() {
    setDraft(toPersonDraft(person));
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
      const fields = personFieldsFromDraft(draft);
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

  return {
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
  };
}

const EMPTY_ADD_PERSON_FORM = { name: "", role: "", email: "", kind: "current" };

/**
 * The "Add person" form's state machine — name/role/email/photo/status,
 * client-side image-type validation (same enforcement EditableImage.jsx uses
 * for the same reason: `accept="image/*"` is a UI hint only). `onAdd(fields,
 * file)` is the caller's own upload+insert+local-state fold-in, typically
 * wired to `addPersonWithPhoto` above.
 */
export function useAddPersonForm(onAdd) {
  const [fields, setFields] = useState(EMPTY_ADD_PERSON_FORM);
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | saving | error
  const [errorMsg, setErrorMsg] = useState("");

  function setField(key, value) {
    setFields((f) => ({ ...f, [key]: value }));
  }

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
      setFields(EMPTY_ADD_PERSON_FORM);
      setFile(null);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  return { fields, setField, file, status, errorMsg, handleFileChange, handleSubmit };
}
