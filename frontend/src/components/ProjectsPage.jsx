import { useEffect, useState } from "react";
import { getProjects } from "../data/db.js";
import Research from "./Research.jsx";

// The full projects index — every project, current and archived. The
// homepage only teases the current ones; this is where "see all N
// projects" links land.
export default function ProjectsPage() {
  const [state, setState] = useState({ loading: true, error: null, projects: null });

  useEffect(() => {
    let alive = true;
    getProjects()
      .then((projects) => alive && setState({ loading: false, error: null, projects }))
      .catch((error) => alive && setState({ loading: false, error, projects: null }));
    return () => {
      alive = false;
    };
  }, []);

  const { loading, error, projects } = state;
  if (error) {
    return (
      <div className="state state--error">
        Couldn’t load projects — {String(error.message || error)}
      </div>
    );
  }
  if (loading) return <div className="state">Loading…</div>;

  return (
    <>
      <p className="breadcrumb">
        <a href="#/">← Back to HCT Lab</a>
      </p>
      <h1>Projects</h1>
      <p className="project-tagline">
        {projects.length} research projects — current work and the lab’s past projects.
      </p>
      <Research projects={projects} />
    </>
  );
}
