import { Suspense, lazy, useEffect, useState } from "react";
import { getSiteContent } from "./data/db.js";
import Header from "./components/Header.jsx";
import { AdminProvider } from "./context/AdminContext.jsx";
import { matchRoute, useHashPath } from "./lib/router.js";

// Each route is its own lazy chunk — visiting the homepage never pulls in the
// samples bake-off UI, and visiting a paper page never pulls in the project
// page's people/roster rendering. Only the active route's code (and only its
// own scoped data) loads.
const SiteHome = lazy(() => import("./components/SiteHome.jsx"));
const ProjectPage = lazy(() => import("./components/ProjectPage.jsx"));
const ProjectsPage = lazy(() => import("./components/ProjectsPage.jsx"));
const PaperPage = lazy(() => import("./components/PaperPage.jsx"));
const PapersPage = lazy(() => import("./components/PapersPage.jsx"));
const Samples = lazy(() => import("./components/Samples.jsx"));
const AdminPage = lazy(() => import("./components/AdminPage.jsx"));

const ROUTES = [
  ["/", "home"],
  ["/projects", "projects-index"],
  ["/projects/:slug", "project"],
  ["/papers", "papers-index"],
  ["/papers/:slug", "paper"],
  ["/samples", "samples"],
  ["/admin", "admin"],
  // Back-compat: the design gallery is now the homepage's built-in selector.
  ["/variants", "home"],
];

function Route({ path, meta }) {
  const match = matchRoute(path, ROUTES);
  if (!match) return <div className="state">Page not found. <a href="#/">Go home</a></div>;
  if (match.value === "home") return <SiteHome meta={meta} />;
  if (match.value === "projects-index") return <ProjectsPage />;
  if (match.value === "project") return <ProjectPage slug={match.params.slug} />;
  if (match.value === "papers-index") return <PapersPage />;
  if (match.value === "paper") return <PaperPage slug={match.params.slug} />;
  if (match.value === "samples") return <Samples />;
  if (match.value === "admin") return <AdminPage />;
  return null;
}

// The homepage is a full-bleed shell that renders its own masthead/footer (per
// selected look), so it opts out of the shared chrome. Everything else keeps it.
function isChromeless(path) {
  const clean = path.split("?")[0].replace(/\/$/, "") || "/";
  return clean === "/" || clean === "/variants";
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

  const body = isChromeless(path) ? (
    <Suspense fallback={<div className="state">Loading…</div>}>
      <Route path={path} meta={meta} />
    </Suspense>
  ) : (
    <main>
      <Header meta={meta} />
      {error && (
        <div className="state state--error">
          Couldn’t reach the lab database — {String(error.message || error)}
        </div>
      )}
      <Suspense fallback={<div className="state">Loading…</div>}>
        <Route path={path} meta={meta} />
      </Suspense>
      <footer>
        Copyright {new Date().getFullYear()} © Human Communication Technologies Lab.{" "}
        <a href="#/" className="footer-link">Home →</a>{" "}
        {/* Deliberately bare (no .footer-link) — inherits the footer's own
            near-invisible color instead of the bright "Home →" blue. A
            low-key entry point for the lab PI, not a public nav item. */}
        <a href="#/admin">Admin</a>
      </footer>
    </main>
  );

  // <AdminProvider> wraps *both* branches, not just the chrome one. The
  // chromeless branch is the site's actual default homepage, and everything
  // it renders — SiteHome, plus Home/People underneath it on Classic — calls
  // useAdmin(), which throws when there's no provider above it. Nothing here
  // is an error boundary, so leaving that branch unwrapped meant a blank page
  // for every visitor to "/".
  return <AdminProvider>{body}</AdminProvider>;
}
