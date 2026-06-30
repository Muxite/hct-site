import { splitByKind, emailLabel, assetUrl } from "../lib/format.js";

const PHOTO_FALLBACK = "/Human Communication Technologies Lab_files/person.png";

// Lab roster, original layout: current members as round-photo tiles, alumni
// grouped beneath under a "year"-style heading.
export default function People({ people, onPersonClick }) {
  const [current, alumni] = splitByKind(people, "alumni");
  if (!current.length && !alumni.length) {
    return <p className="state">Roster coming soon.</p>;
  }
  return (
    <>
      <div className="wrapper" id="people">
        {current.map((p) => (
          <PersonTile key={p.name} person={p} onPersonClick={onPersonClick} />
        ))}
      </div>
      {alumni.length > 0 && (
        <>
          <h3 className="year">Alumni</h3>
          <div className="wrapper" id="alumni">
            {alumni.map((p) => (
              <PersonTile key={p.name} person={p} onPersonClick={onPersonClick} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function PersonTile({ person, onPersonClick }) {
  const photo = person.photo ? assetUrl(person.photo) : PHOTO_FALLBACK;
  return (
    <div
      className="person-tile"
      style={{ cursor: "pointer" }}
      onClick={() => onPersonClick && onPersonClick(person.name)}
      title={`View publications by ${person.name}`}
    >
      <div className="photo">
        <img
          alt={person.name}
          src={photo}
          loading="lazy"
          onError={(e) => {
            e.currentTarget.onerror = null;
            e.currentTarget.src = PHOTO_FALLBACK;
          }}
        />
      </div>
      <div className="info">
        <strong>{person.name}</strong>
        {person.role && (
          <div className="project" style={{ whiteSpace: "nowrap" }}>
            {person.role}
          </div>
        )}
        {person.email && (
          <div className="email">
            <a
              href={`mailto:${person.email}`}
              onClick={(e) => e.stopPropagation()}
            >
              {emailLabel(person.email)}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

