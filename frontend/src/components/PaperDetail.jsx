import { useEffect, useState } from "react";
import { getPublication } from "../data/db.js";
import { formatAuthors, typeLabel } from "../lib/format.js";

// Per-paper page reached via ?paper=<slug>. Shows the full metadata, the
// lab-voice description, the source link, and the BibTeX (collapsible).
export default function PaperDetail({ slug, meta, onBack }) {
  const [pub, setPub] = useState(undefined); // undefined=loading, null=missing

  useEffect(() => {
    let alive = true;
    getPublication(slug)
      .then((p) => alive && setPub(p))
      .catch(() => alive && setPub(null));
    return () => {
      alive = false;
    };
  }, [slug]);

  return (
    <article className="paper">
      <div className="paper__nav">
        <a
          href={window.location.pathname}
          onClick={(e) => {
            e.preventDefault();
            onBack();
          }}
        >
          ← {meta.title || "HCT Lab"}
        </a>
      </div>

      {pub === undefined && <p className="state state--loading">Loading…</p>}
      {pub === null && (
        <div className="state">
          <h1>Not found</h1>
          <p className="muted">No publication matches “{slug}”.</p>
        </div>
      )}
      {pub && (
        <div className="paper__body">
          <span className="paper__kicker">
            {typeLabel(pub.type)} · {pub.year}
          </span>
          <h1 className="paper__title">{pub.title}</h1>
          <p className="paper__authors">{formatAuthors(pub.authors)}</p>
          {pub.venue && <p className="paper__venue">{pub.venue}</p>}
          {pub.description && <p className="paper__desc">{pub.description}</p>}
          <div className="paper__links">
            {pub.link && (
              <a href={pub.link} target="_blank" rel="noreferrer">
                Read the paper →
              </a>
            )}
          </div>
          {pub.bibtex && (
            <details className="paper__bibtex">
              <summary>BibTeX</summary>
              <pre>{pub.bibtex}</pre>
            </details>
          )}
        </div>
      )}
    </article>
  );
}
