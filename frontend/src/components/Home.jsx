import { useEffect, useState } from "react";
import { getPeople, getProjects, getSiteContent, updateSiteContent } from "../data/db.js";
import { useAdmin } from "../context/AdminContext.jsx";
import EditableText from "./EditableText.jsx";
import Prose from "./Prose.jsx";
import People from "./People.jsx";
import Research from "./Research.jsx";
import Publications from "./Publications.jsx";

const PROSE_TITLES = {
  vision: "Vision",
  innovation: "Innovation",
  contact: "Contact",
  land_acknowledgment: "Land Acknowledgment",
  edi: "Equity, Diversity, Inclusion + Indigeneity",
  sponsors: "Sponsors",
  opportunities: "Opportunities",
};

// The homepage: lab intro -> people -> project grid (leads with the plain-
// language project pages) -> full publication timeline. Only fetches the
// small tables (people, projects, prose) up front; the 550+ row publication
// list is paginated by <Publications> itself.
export default function Home() {
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getPeople(), getProjects(), getSiteContent()])
      .then(([people, projects, content]) => ({ people, projects, content }))
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return (
      <div className="state state--error">
        Couldn’t reach the lab database — {String(error.message || error)}
      </div>
    );
  }
  if (!data) {
    return <div className="state">Loading…</div>;
  }

  const { content, people, projects } = data;

  // Persists the edit, then folds the same value into local state so the
  // read view (which renders straight from `content[key]`, not from
  // EditableText's own state) reflects it without a full refetch.
  async function saveContent(key, nextText) {
    const nextValue = { ...(content[key] || { title: PROSE_TITLES[key] }), text: nextText };
    await updateSiteContent(key, nextValue);
    setData((d) => ({ ...d, content: { ...d.content, [key]: nextValue } }));
  }

  const proseSection = (key) => {
    const v = content[key];
    // Public visitors never see an empty section; an admin in edit mode gets
    // an affordance to add the missing text instead of the block vanishing.
    if ((!v || !v.text) && !editable) return null;
    const text = v?.text || "";
    return (
      <div className="prose-block" key={key}>
        <h2>{PROSE_TITLES[key]}</h2>
        <EditableText
          value={text}
          editable={editable}
          multiline
          placeholder="Add text for this section…"
          render={(t) => (t ? <Prose text={t} /> : null)}
          onSave={(nextText) => saveContent(key, nextText)}
        />
      </div>
    );
  };

  return (
    <>
      <div className="two-col">
        {proseSection("vision")}
        {proseSection("innovation")}
      </div>

      <h2>People</h2>
      <People people={people} />

      <h2>Projects</h2>
      <Research projects={projects} />
      <div className="note">
        For past projects, see our old HCT site{" "}
        <a href="https://hct.ece.ubc.ca/research">research page</a>.
      </div>

      {proseSection("contact")}
      {proseSection("land_acknowledgment")}
      {proseSection("edi")}
      {proseSection("sponsors")}
      {proseSection("opportunities")}

      <h2 className="section" id="publications">
        Publications
      </h2>
      <Publications />
    </>
  );
}
