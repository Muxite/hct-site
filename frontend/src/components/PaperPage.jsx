import { useEffect, useState } from "react";
import Prose from "./Prose.jsx";
import { assetUrl, formatAuthors, typeLabel, paperImagePath } from "../lib/format.js";
import { getPublication, updatePublication } from "../data/db.js";
import { uploadToSiteMedia } from "../data/storage.js";
import { useAdmin } from "../context/AdminContext.jsx";
import EditableText from "./EditableText.jsx";
import EditableImage from "./EditableImage.jsx";

// A single paper's page: representative image, plain-language summary (style
// A) as the body for the general public, with the technical abstract (style
// B) and problem/approach/result breakdown (style C) available as expandable
// sections for researchers and prospective grad students respectively.
// Bibliographic fields (title/authors/venue/DOI/bibtex) are read-only here —
// they come from the CV parse (backend/src/cv_parse.py), not admin edits;
// only the three prose summaries and the image are editable, matching
// db/schema.sql's `publications_admin_guard` trigger.
export default function PaperPage({ slug }) {
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;
  const [state, setState] = useState({ loading: true, error: null, pub: null });
  const [open, setOpen] = useState({ abstract: false, par: false });

  useEffect(() => {
    let alive = true;
    setState({ loading: true, error: null, pub: null });
    setOpen({ abstract: false, par: false });
    getPublication(slug)
      .then((pub) => alive && setState({ loading: false, error: null, pub }))
      .catch((error) => alive && setState({ loading: false, error, pub: null }));
    return () => {
      alive = false;
    };
  }, [slug]);

  const { loading, error, pub } = state;
  if (error) {
    return (
      <div className="state state--error">
        Couldn’t load this paper — {String(error.message || error)}
      </div>
    );
  }
  if (loading) return <div className="state">Loading…</div>;
  if (!pub) return <div className="state">Paper not found.</div>;

  // Folds a known-good field value into local state. updatePublication's
  // `.select()` uses PUB_COLS_FULL (data/db.js), which — unlike
  // updateProject's PROJECT_GRID_COLS — already covers summary_plain/
  // summary_abstract/summary_par/image, so `saved` is trustworthy; the
  // `fields` fallback only matters if `.maybeSingle()` ever comes back empty.
  function patchPub(fields, saved) {
    setState((s) => ({ ...s, pub: { ...s.pub, ...(saved || fields) } }));
  }

  async function handleImageSave(file) {
    const url = await uploadToSiteMedia(file, paperImagePath(pub.slug, file));
    const saved = await updatePublication(pub.slug, { image: url });
    patchPub({ image: url }, saved);
  }

  async function handleSummaryPlainSave(nextText) {
    const saved = await updatePublication(pub.slug, { summary_plain: nextText });
    patchPub({ summary_plain: nextText }, saved);
  }

  async function handleSummaryAbstractSave(nextText) {
    const saved = await updatePublication(pub.slug, { summary_abstract: nextText });
    patchPub({ summary_abstract: nextText }, saved);
  }

  async function handleSummaryParSave(nextText) {
    const saved = await updatePublication(pub.slug, { summary_par: nextText });
    patchPub({ summary_par: nextText }, saved);
  }

  return (
    <article className="paper-page">
      <p className="breadcrumb">
        {pub.project_slug ? (
          <a href={`#/projects/${pub.project_slug}`}>← Back to project</a>
        ) : (
          <a href="#/">← Back to HCT Lab</a>
        )}
      </p>

      {(pub.image || editable) && (
        <div className="paper-hero">
          {editable ? (
            <EditableImage value={pub.image} onSave={handleImageSave} editable alt={pub.title} />
          ) : (
            pub.image && <img alt={pub.title} src={assetUrl(pub.image)} loading="lazy" />
          )}
        </div>
      )}

      <h1>{pub.title}</h1>
      <div className="pub-meta">
        {formatAuthors(pub.authors)}
        <br />
        {pub.venue ? `${pub.venue}, ` : ""}
        {pub.year}. [{typeLabel(pub.type)}]
      </div>
      <p className="paper-links">
        {pub.link ? (
          <a href={pub.link} target="_blank" rel="noreferrer">
            article link
          </a>
        ) : (
          <strike>link</strike>
        )}
      </p>

      <EditableText
        value={pub.summary_plain || ""}
        editable={editable}
        multiline
        placeholder="Add a plain-language summary…"
        render={(t) => {
          const text = t || pub.description || "";
          return text ? <Prose text={text} /> : <p className="state">Summary coming soon.</p>;
        }}
        onSave={handleSummaryPlainSave}
      />

      {(pub.summary_abstract || editable) && (
        <Expandable
          label="Technical abstract"
          open={open.abstract}
          onToggle={() => setOpen((o) => ({ ...o, abstract: !o.abstract }))}
        >
          <EditableText
            value={pub.summary_abstract || ""}
            editable={editable}
            multiline
            placeholder="Add the technical abstract…"
            render={(t) => (t ? <Prose text={t} /> : <p className="state">No abstract yet.</p>)}
            onSave={handleSummaryAbstractSave}
          />
        </Expandable>
      )}

      {(pub.summary_par || editable) && (
        <Expandable
          label="Problem / Approach / Result"
          open={open.par}
          onToggle={() => setOpen((o) => ({ ...o, par: !o.par }))}
        >
          <EditableText
            value={pub.summary_par || ""}
            editable={editable}
            multiline
            placeholder="Add the problem / approach / result summary…"
            render={(t) => (t ? <Prose text={t} /> : <p className="state">Nothing here yet.</p>)}
            onSave={handleSummaryParSave}
          />
        </Expandable>
      )}

      {pub.bibtex && (
        <Expandable
          label="BibTeX"
          open={open.bibtex}
          onToggle={() => setOpen((o) => ({ ...o, bibtex: !o.bibtex }))}
        >
          <pre className="bibtex">{pub.bibtex}</pre>
        </Expandable>
      )}
    </article>
  );
}

function Expandable({ label, open, onToggle, children }) {
  return (
    <div className="expandable">
      <button type="button" className="expandable__toggle" onClick={onToggle}>
        {open ? "▾" : "▸"} {label}
      </button>
      {open && <div className="expandable__body">{children}</div>}
    </div>
  );
}
