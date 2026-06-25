import { useState } from "react";
import { groupByYear, formatAuthors, typeLabel } from "../lib/format.js";

// Publications: the lab's full history, grouped by year (newest first), in the
// original site's flat list style — authors, title, venue/year, [type], and an
// inline link plus a collapsible BibTeX block.
export default function Publications({ publications }) {
  const groups = groupByYear(publications);
  if (!groups.length) {
    return <div id="publications-list" className="state">No publications yet.</div>;
  }
  return (
    <div id="publications-list">
      {groups.map(([year, items]) => (
        <div key={year}>
          <h3 className="year">{year}</h3>
          {items.map((p, i) => (
            <PubEntry key={p.slug || `${year}-${i}`} pub={p} />
          ))}
        </div>
      ))}
    </div>
  );
}

function PubEntry({ pub }) {
  const [showBib, setShowBib] = useState(false);
  const venue = pub.venue ? `${pub.venue}, ` : "";
  return (
    <div className="pub">
      <div>{formatAuthors(pub.authors)}</div>
      <div className="pub-title">{pub.title}</div>
      <div className="pub-meta">
        {venue}
        {pub.year}. [{typeLabel(pub.type)}]
      </div>
      <div className="pub-links">
        {pub.link ? (
          <a href={pub.link} target="_blank" rel="noreferrer">
            link
          </a>
        ) : (
          <strike>link</strike>
        )}{" "}
        /{" "}
        {pub.bibtex ? (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setShowBib((v) => !v);
            }}
          >
            bibtex
          </a>
        ) : (
          <strike>bibtex</strike>
        )}
      </div>
      {pub.bibtex && showBib && <pre className="bibtex">{pub.bibtex}</pre>}
    </div>
  );
}
