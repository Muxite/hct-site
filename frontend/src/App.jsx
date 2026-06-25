import { useEffect, useState } from "react";
import {
  getPublications,
  getPeople,
  getResearch,
  getSiteContent,
} from "./data/db.js";
import Header from "./components/Header.jsx";
import Prose from "./components/Prose.jsx";
import People from "./components/People.jsx";
import Research from "./components/Research.jsx";
import Publications from "./components/Publications.jsx";

// The site mirrors the original hct-lab.github.io layout, but every section is
// rendered live from Supabase (publications, people, research, and the prose
// blocks) instead of baked-in markup. Everything loads in one pass on mount.
//
// Section headings match the original site verbatim.
const PROSE_TITLES = {
  vision: "Vision",
  innovation: "Innovation",
  contact: "Contact",
  land_acknowledgment: "Land Acknowledgment",
  edi: "Equity, Diversity, Inclusion + Indigeneity",
  sponsors: "Sponsors",
  opportunities: "Opportunities",
};

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getPublications(), getPeople(), getResearch(), getSiteContent()])
      .then(([publications, people, research, content]) => {
        if (alive) setData({ publications, people, research, content });
      })
      .catch((err) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return (
      <main>
        <div className="state state--error">
          Couldn’t reach the lab database — {String(error.message || error)}
        </div>
      </main>
    );
  }
  if (!data) {
    return (
      <main>
        <div className="state">Loading…</div>
      </main>
    );
  }

  const content = data.content;
  const meta = content.site_meta || {};

  // A prose section renders only when its site_content row exists.
  const proseSection = (key) => {
    const v = content[key];
    if (!v || !v.text) return null;
    return (
      <div key={key}>
        <h2>{PROSE_TITLES[key]}</h2>
        <Prose text={v.text} />
      </div>
    );
  };

  return (
    <main>
      <Header meta={meta} />

      {proseSection("vision")}
      {proseSection("innovation")}

      <h2>People</h2>
      <People people={data.people} />

      <h2>Research</h2>
      <Research projects={data.research} />
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
      <Publications publications={data.publications} />

      <footer>
        Copyright {new Date().getFullYear()} © Human Communication Technologies Lab.
      </footer>
    </main>
  );
}
