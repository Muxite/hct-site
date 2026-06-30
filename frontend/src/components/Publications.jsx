import { useState } from "react";
import { groupByYear, formatAuthors, typeLabel } from "../lib/format.js";

export default function Publications({ publications, authorFilter, onClearAuthor }) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTime, setSelectedTime] = useState("all");
  const [selectedType, setSelectedType] = useState("all");

  const currentYear = new Date().getFullYear();

  // Extract unique types from data for the filter dropdown
  const uniqueTypes = [...new Set((publications || []).map((p) => p.type).filter(Boolean))];

  // Filter publications list
  const filtered = (publications || []).filter((p) => {
    // 0. Author filter (from clicking a person tile)
    if (authorFilter) {
      const hasAuthor = (p.authors || []).some(
        (a) => a.toLowerCase().includes(authorFilter.toLowerCase()),
      );
      if (!hasAuthor) return false;
    }

    // 1. Search Query filter (title, venue, authors, year)
    const matchesQuery =
      !searchQuery ||
      [p.title, p.venue, ...(p.authors || []), String(p.year)].some((field) =>
        String(field || "").toLowerCase().includes(searchQuery.toLowerCase()),
      );

    // 2. Time / Year filter
    let matchesTime = true;
    if (selectedTime !== "all") {
      if (selectedTime === "last3") {
        matchesTime = p.year >= currentYear - 2;
      } else if (selectedTime === "last5") {
        matchesTime = p.year >= currentYear - 4;
      } else if (selectedTime === "last10") {
        matchesTime = p.year >= currentYear - 9;
      } else {
        matchesTime = String(p.year) === selectedTime;
      }
    }

    // 3. Type filter
    const matchesType = selectedType === "all" || p.type === selectedType;

    return matchesQuery && matchesTime && matchesType;
  });

  const groups = groupByYear(filtered);

  // Extract unique years from the full dataset for the select options
  const uniqueYears = [...new Set((publications || []).map((p) => p.year).filter(Boolean))].sort((a, b) => b - a);

  return (
    <div id="publications-list">
      {/* Author filter banner */}
      {authorFilter && (
        <div className="pub-author-banner">
          Showing publications by <strong>{authorFilter}</strong>.{" "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              onClearAuthor && onClearAuthor();
            }}
          >
            Show all
          </a>
        </div>
      )}

      {/* Search and Filters Panel */}
      <div className="pub-filter-controls">
        <input
          type="text"
          className="pub-search-input"
          placeholder="Search publications..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        
        <select
          className="pub-select"
          value={selectedTime}
          onChange={(e) => setSelectedTime(e.target.value)}
        >
          <option value="all">All Years</option>
          <option value="last3">Last 3 Years</option>
          <option value="last5">Last 5 Years</option>
          <option value="last10">Last 10 Years</option>
          <optgroup label="Specific Year">
            {uniqueYears.map((yr) => (
              <option key={yr} value={String(yr)}>
                {yr}
              </option>
            ))}
          </optgroup>
        </select>

        <select
          className="pub-select"
          value={selectedType}
          onChange={(e) => setSelectedType(e.target.value)}
        >
          <option value="all">All Types</option>
          {uniqueTypes.map((t) => (
            <option key={t} value={t}>
              {typeLabel(t)}
            </option>
          ))}
        </select>
      </div>

      <div className="pub-filter-stats" style={{ marginBottom: "20px" }}>
        <div>
          Showing {filtered.length} of {publications.length} publications
        </div>
        {(searchQuery || selectedTime !== "all" || selectedType !== "all" || authorFilter) && (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setSearchQuery("");
              setSelectedTime("all");
              setSelectedType("all");
              onClearAuthor && onClearAuthor();
            }}
          >
            Reset filters
          </a>
        )}
      </div>

      {/* Render Grouped Publications */}
      {groups.length > 0 ? (
        groups.map(([year, items]) => (
          <div key={year}>
            <h3 className="year">{year}</h3>
            {items.map((p, i) => (
              <PubEntry key={p.slug || `${year}-${i}`} pub={p} />
            ))}
          </div>
        ))
      ) : (
        <div className="state">No publications matched your filters.</div>
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
