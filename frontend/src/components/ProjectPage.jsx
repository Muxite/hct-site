import { useEffect, useState } from "react";
import Prose from "./Prose.jsx";
import { assetUrl, formatAuthors, emailLabel } from "../lib/format.js";
import { getProject, getProjectPeople, getPeopleByNames, getProjectPapers } from "../data/db.js";

const PHOTO_FALLBACK = "/Human Communication Technologies Lab_files/person.png";

// A single project's page: hero image, longer summary, the lab people
// involved, and its member papers (small image + plain-language excerpt).
// Fetches only this one project's rows — never the whole projects/people/
// publications tables.
export default function ProjectPage({ slug }) {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    let alive = true;
    setState({ loading: true, error: null, data: null });
    Promise.all([getProject(slug), getProjectPeople(slug), getProjectPapers(slug)])
      .then(async ([project, links, papers]) => {
        const people = await getPeopleByNames(links.map((l) => l.person_name));
        const byName = Object.fromEntries(people.map((p) => [p.name, p]));
        const roster = links.map((l) => ({ ...byName[l.person_name], ...l }));
        return { project, roster, papers };
      })
      .then((data) => alive && setState({ loading: false, error: null, data }))
      .catch((error) => alive && setState({ loading: false, error, data: null }));
    return () => {
      alive = false;
    };
  }, [slug]);

  const { loading, error, data } = state;
  if (error) {
    return (
      <div className="state state--error">
        Couldn’t load this project — {String(error.message || error)}
      </div>
    );
  }
  if (loading) return <div className="state">Loading…</div>;
  if (!data?.project) return <div className="state">Project not found.</div>;

  const { project, roster, papers } = data;
  const hero = project.hero_image || project.image;

  return (
    <article className="project-page">
      <p className="breadcrumb">
        <a href="#/">← Back to HCT Lab</a>
      </p>

      {hero && (
        <div className="project-hero">
          <img alt={project.title} src={assetUrl(hero)} loading="lazy" />
        </div>
      )}

      <h1>{project.title}</h1>
      {project.tagline && <p className="project-tagline">{project.tagline}</p>}
      {project.link && (
        <p>
          <a href={project.link} target="_blank" rel="noreferrer">
            Project site
          </a>
        </p>
      )}

      <Prose text={project.summary || project.description || ""} />

      {roster.length > 0 && (
        <>
          <h2>People on this project</h2>
          <div className="wrapper">
            {roster.map((p) => (
              <div className="person-tile" key={p.person_name}>
                <div className="photo">
                  <img
                    alt={p.person_name}
                    src={p.photo ? assetUrl(p.photo) : PHOTO_FALLBACK}
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.onerror = null;
                      e.currentTarget.src = PHOTO_FALLBACK;
                    }}
                  />
                </div>
                <div className="info">
                  <strong>{p.person_name}</strong>
                  {(p.role_on_project || p.role) && (
                    <div className="project">{p.role_on_project || p.role}</div>
                  )}
                  {p.email && (
                    <div className="email">
                      <a href={`mailto:${p.email}`}>{emailLabel(p.email)}</a>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <h2>Papers</h2>
      {!papers.length && <p className="state">No papers assigned to this project yet.</p>}
      {papers.map((p) => (
        <a className="project-paper" href={`#/papers/${p.slug}`} key={p.slug}>
          <div className="project-paper__photo">
            {p.image && <img alt="" src={assetUrl(p.image)} loading="lazy" />}
          </div>
          <div className="project-paper__info">
            <div className="project-paper__title">{p.title}</div>
            <div className="pub-meta">
              {formatAuthors(p.authors)}
              {p.venue ? ` · ${p.venue}` : ""} · {p.year}
            </div>
            {p.summary_plain && <p className="project-paper__excerpt">{p.summary_plain}</p>}
          </div>
        </a>
      ))}
    </article>
  );
}
