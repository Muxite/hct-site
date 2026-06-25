import { splitByKind, assetUrl } from "../lib/format.js";

// Research projects, original layout: square rounded-image tiles. Current
// projects first, then archived. The short tagline is preferred for the tile
// (the longer AI description reads as the blurb when no tagline exists).
export default function Research({ projects }) {
  const [current, archived] = splitByKind(projects, "archived");
  if (!current.length && !archived.length) {
    return <p className="state">Projects coming soon.</p>;
  }
  return (
    <div className="wrapper" id="research">
      {[...current, ...archived].map((r) => (
        <ResearchTile key={r.title} project={r} />
      ))}
    </div>
  );
}

function ResearchTile({ project }) {
  const blurb = project.tagline || project.description || "";
  const inner = (
    <>
      <div className="photo">
        {project.image && (
          <img
            alt={project.title}
            src={assetUrl(project.image)}
            loading="lazy"
            onError={(e) => {
              const wrap = e.currentTarget.closest(".photo");
              if (wrap) wrap.style.visibility = "hidden";
            }}
          />
        )}
      </div>
      <div className="info">
        <h3>{project.title}</h3>
        {blurb && <h4>{blurb}</h4>}
      </div>
    </>
  );
  return project.link ? (
    <a className="research-tile" href={project.link} target="_blank" rel="noreferrer">
      {inner}
    </a>
  ) : (
    <div className="research-tile">{inner}</div>
  );
}
