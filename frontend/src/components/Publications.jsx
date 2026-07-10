import { useEffect, useState } from "react";
import { groupByYear, formatAuthors, typeLabel } from "../lib/format.js";
import { getPublicationsPage } from "../data/db.js";

const PAGE_SIZE = 40;

// Publications: the lab's full history, grouped by year (newest first), in the
// original site's flat list style — authors, title, venue/year, [type], and an
// inline link plus a collapsible BibTeX block. Loaded a page at a time (551+
// rows total) rather than all at once — "Load more" fetches the next slice.
export default function Publications() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadMore = (offset) => {
    setLoading(true);
    getPublicationsPage({ offset, limit: PAGE_SIZE })
      .then(({ rows: page, total: t }) => {
        setRows((prev) => (offset === 0 ? page : [...prev, ...page]));
        setTotal(t);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadMore(0);
  }, []);

  if (error) {
    return (
      <div id="publications-list" className="state state--error">
        Couldn’t load publications — {String(error.message || error)}
      </div>
    );
  }
  const groups = groupByYear(rows);
  if (!groups.length && loading) {
    return <div id="publications-list" className="state">Loading…</div>;
  }
  if (!groups.length) {
    return <div id="publications-list" className="state">No publications yet.</div>;
  }
  const hasMore = total != null && rows.length < total;
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
      {hasMore && (
        <button
          type="button"
          className="load-more"
          onClick={() => loadMore(rows.length)}
          disabled={loading}
        >
          {loading ? "Loading…" : `Load more (${rows.length} of ${total})`}
        </button>
      )}
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
