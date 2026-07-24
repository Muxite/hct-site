import Publications from "./Publications.jsx";

// The full publications index — the lab's entire history, unpaginated-teaser
// (loads a page at a time via "Load more"). The homepage only teases a
// handful of the most recent papers; this is where "see all N publications"
// links land.
export default function PapersPage() {
  return (
    <>
      <p className="breadcrumb">
        <a href="#/">← Back to HCT Lab</a>
      </p>
      <h1 className="section">Publications</h1>
      <Publications />
    </>
  );
}
