import { useAdmin } from "../context/AdminContext.jsx";
import "../admin.css";

/**
 * Fixed on-screen flag for the dev-only `VITE_ADMIN_PREVIEW` override (see
 * lib/adminPreview.js + .env.example) — renders nothing at all unless that
 * override is actually active, so a screenshot taken under it can never be
 * mistaken for a real logged-in admin session.
 *
 * Rendered once from App.jsx (a sibling of the routed page, like Feedback.jsx)
 * so it shows up on every route, including the chromeless homepage — the
 * pages the override actually affects (Home.jsx/People.jsx/ProjectPage.jsx/
 * PaperPage.jsx/SiteHome.jsx all gate their edit affordances on
 * `isAdmin && editMode`, which this override forces true).
 *
 * This is a QA/screenshot safety label, not a security boundary: the override
 * never creates a real Supabase session, so nothing this banner announces
 * grants any actual write access — a real admin JWT is still required
 * server-side (RLS, `api/_lib/verifyAdmin.js`) for any Save/Upload button the
 * preview UI happens to render to actually succeed.
 */
export default function AdminPreviewBanner() {
  const { adminPreview } = useAdmin();
  if (!adminPreview) return null;
  return (
    <div className="admin-preview-banner" role="status">
      ADMIN PREVIEW — VITE_ADMIN_PREVIEW is forcing isAdmin/editMode. No real
      session. Dev-only, never shipped to production.
    </div>
  );
}
