import { splitByKind } from "../lib/format.js";

// Research projects: current first, archived ("Past Projects") beneath. Each
// tile links out to its project page; the AI description is preferred over the
// short tagline when present.
export default function Research({ projects }) {
  const [current, archived] = splitByKind(projects, "archived");
  if (!current.length && !archived.length) {
    return <p className="muted">Projects coming soon.</p>;
  }
  return (
    <>
      <div className="research-grid">
        {current.map((r) => (
          <ResearchTile key={r.title} project={r} />
        ))}
      </div>
      {archived.length > 0 && (
        <>
          <h3 className="subgroup">Past Projects</h3>
          <div className="research-grid">
            {archived.map((r) => (
              <ResearchTile key={r.title} project={r} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function ResearchTile({ project }) {
  const blurb = project.description || project.tagline || "";
  const Tag = project.link ? "a" : "div";
  const props = project.link
    ? { href: project.link, target: "_blank", rel: "noreferrer" }
    : {};
  return (
    <Tag className="research-tile" {...props}>
      {project.image && (
        <div className="research-tile__photo">
          <img
            src={project.image}
            alt={project.title}
            loading="lazy"
            onError={(e) => {
              const wrap = e.currentTarget.closest(".research-tile__photo");
              if (wrap) wrap.style.display = "none";
            }}
          />
        </div>
      )}
      <div className="research-tile__info">
        <h4 className="research-tile__title">{project.title}</h4>
        {blurb && <p className="research-tile__blurb">{blurb}</p>}
        {project.link && <span className="research-tile__cta">View project →</span>}
      </div>
    </Tag>
  );
}
