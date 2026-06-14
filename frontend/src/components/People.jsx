import { splitByKind, emailLabel } from "../lib/format.js";

// Lab roster: current members in a grid, alumni grouped beneath. Photos fall
// back to a monogram tile when missing or broken.
export default function People({ people }) {
  const [current, alumni] = splitByKind(people, "alumni");
  if (!current.length && !alumni.length) {
    return <p className="muted">Roster coming soon.</p>;
  }
  return (
    <>
      <div className="people-grid">
        {current.map((p) => (
          <PersonCard key={p.name} person={p} />
        ))}
      </div>
      {alumni.length > 0 && (
        <>
          <h3 className="subgroup">Alumni</h3>
          <div className="people-grid people-grid--alumni">
            {alumni.map((p) => (
              <PersonCard key={p.name} person={p} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function PersonCard({ person }) {
  return (
    <article className="person">
      <Photo name={person.name} src={person.photo} />
      <div className="person__info">
        <h4 className="person__name">{person.name}</h4>
        {person.role && <p className="person__role">{person.role}</p>}
        {person.email && (
          <a className="person__email" href={`mailto:${person.email}`}>
            {emailLabel(person.email)}
          </a>
        )}
        {person.bio && <p className="person__bio">{person.bio}</p>}
      </div>
    </article>
  );
}

function Photo({ name, src }) {
  const monogram = (name || "?").trim().charAt(0).toUpperCase();
  if (!src) return <div className="person__photo person__photo--blank">{monogram}</div>;
  return (
    <img
      className="person__photo"
      src={src}
      alt={name}
      loading="lazy"
      onError={(e) => {
        e.currentTarget.replaceWith(
          Object.assign(document.createElement("div"), {
            className: "person__photo person__photo--blank",
            textContent: monogram,
          }),
        );
      }}
    />
  );
}
