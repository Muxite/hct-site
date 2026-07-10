import { Suspense, lazy, useEffect, useState } from "react";
import { getSiteContent } from "./data/db.js";
import Header from "./components/Header.jsx";
import { matchRoute, useHashPath } from "./lib/router.js";

// Each route is its own lazy chunk — visiting the homepage never pulls in the
// samples bake-off UI, and visiting a paper page never pulls in the project
// page's people/roster rendering. Only the active route's code (and only its
// own scoped data) loads.
const Home = lazy(() => import("./components/Home.jsx"));
const ProjectPage = lazy(() => import("./components/ProjectPage.jsx"));
const PaperPage = lazy(() => import("./components/PaperPage.jsx"));
const Samples = lazy(() => import("./components/Samples.jsx"));

const ROUTES = [
  ["/", "home"],
  ["/projects/:slug", "project"],
  ["/papers/:slug", "paper"],
  ["/samples", "samples"],
];

function Route({ path }) {
  const match = matchRoute(path, ROUTES);
  if (!match) return <div className="state">Page not found. <a href="#/">Go home</a></div>;
  if (match.value === "home") return <Home />;
  if (match.value === "project") return <ProjectPage slug={match.params.slug} />;
  if (match.value === "paper") return <PaperPage slug={match.params.slug} />;
  if (match.value === "samples") return <Samples />;
  return null;
}

export default function App() {
  const path = useHashPath();
  const [meta, setMeta] = useState({});
  const [error, setError] = useState(null);

  // Header chrome (title/subtitle/tagline) is the same on every route and is
  // a single tiny site_content read — fetched once here, not per-route.
  useEffect(() => {
    let alive = true;
    getSiteContent()
      .then((content) => alive && setMeta(content.site_meta || {}))
      .catch((err) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main>
      <Header meta={meta} />
      {error && (
        <div className="state state--error">
          Couldn’t reach the lab database — {String(error.message || error)}
        </div>
      )}
      <Suspense fallback={<div className="state">Loading…</div>}>
        <Route path={path} />
      </Suspense>
      <footer>
        Copyright {new Date().getFullYear()} © Human Communication Technologies Lab.
      </footer>
    </main>
  );
}
