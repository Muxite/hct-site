import { groupByYear, formatAuthors } from "../lib/format.js";

/**
 * The centerpiece: the lab's full publication history, grouped by year (newest
 * first) along a vertical year-spined rail. Each entry links to its detail page.
 */
export default function Timeline({ entries, onSelect }) {
  const groups = groupByYear(entries);
  if (groups.length === 0) {
    return <p className="muted">No publications yet.</p>;
  }
  return (
    <ol className="timeline">
      {groups.map(([year, items]) => (
        <li className="timeline__year" key={year}>
          <div className="timeline__marker">{year}</div>
          <ul className="timeline__entries">
            {items.map((e, i) => (
              <TimelineEntry key={e.slug || `${year}-${i}`} entry={e} onSelect={onSelect} />
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

function TimelineEntry({ entry, onSelect }) {
  const authors = formatAuthors(entry.authors);
  const clickable = Boolean(entry.slug);
  return (
    <li className="entry">
      {clickable ? (
        <a
          className="entry__title"
          href={`?paper=${encodeURIComponent(entry.slug)}`}
          onClick={(ev) => {
            ev.preventDefault();
            onSelect(entry.slug);
          }}
        >
          {entry.title}
        </a>
      ) : (
        <span className="entry__title">{entry.title}</span>
      )}
      {authors && <p className="entry__authors">{authors}</p>}
      {entry.blurb && <p className="entry__blurb">{entry.blurb}</p>}
    </li>
  );
}
