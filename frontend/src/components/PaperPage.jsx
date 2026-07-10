import { useEffect, useState } from "react";
import Prose from "./Prose.jsx";
import { assetUrl, formatAuthors, typeLabel } from "../lib/format.js";
import { getPublication } from "../data/db.js";

// A single paper's page: representative image, plain-language summary (style
// A) as the body for the general public, with the technical abstract (style
// B) and problem/approach/result breakdown (style C) available as expandable
// sections for researchers and prospective grad students respectively.
export default function PaperPage({ slug }) {
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

  const body = pub.summary_plain || pub.description || "";

  return (
    <article className="paper-page">
      <p className="breadcrumb">
        {pub.project_slug ? (
          <a href={`#/projects/${pub.project_slug}`}>← Back to project</a>
        ) : (
          <a href="#/">← Back to HCT Lab</a>
        )}
      </p>

      {pub.image && (
        <div className="paper-hero">
          <img alt={pub.title} src={assetUrl(pub.image)} loading="lazy" />
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

      {body ? <Prose text={body} /> : <p className="state">Summary coming soon.</p>}

      {pub.summary_abstract && (
        <Expandable
          label="Technical abstract"
          open={open.abstract}
          onToggle={() => setOpen((o) => ({ ...o, abstract: !o.abstract }))}
        >
          <Prose text={pub.summary_abstract} />
        </Expandable>
      )}

      {pub.summary_par && (
        <Expandable
          label="Problem / Approach / Result"
          open={open.par}
          onToggle={() => setOpen((o) => ({ ...o, par: !o.par }))}
        >
          <Prose text={pub.summary_par} />
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
