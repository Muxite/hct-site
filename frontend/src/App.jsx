import { useEffect, useState } from "react";
import {
  getPublications,
  getPeople,
  getResearch,
  getSiteContent,
  getPaperSamples,
} from "./data/db.js";
import Header from "./components/Header.jsx";
import Prose from "./components/Prose.jsx";
import People from "./components/People.jsx";
import Research from "./components/Research.jsx";
import Publications from "./components/Publications.jsx";
import Samples from "./components/Samples.jsx";

const PROSE_TITLES = {
  vision: "Vision",
  innovation: "Innovation",
  contact: "Contact",
  land_acknowledgment: "Land Acknowledgment",
  edi: "Equity, Diversity, Inclusion + Indigeneity",
  sponsors: "Sponsors",
  opportunities: "Opportunities",
};

const IS_SAMPLES =
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).has("samples");

function SamplesCallout({ samples }) {
  const paperCount = new Set((samples || []).map((s) => s.paper_slug)).size;
  if (!paperCount) return null;
  return (
    <aside className="samples-callout">
      <div>
        <strong>Paper page style samples</strong>
        <p>
          The agent retrieved article context for {paperCount} research papers and
          drafted five paragraph styles for each one.
        </p>
      </div>
      <a href="/?samples">Review options</a>
    </aside>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [authorFilter, setAuthorFilter] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = IS_SAMPLES
      ? Promise.all([getPaperSamples(), getPublications()]).then(
          ([samples, publications]) => ({ samples, publications }),
        )
      : Promise.all([
          getPublications(),
          getPeople(),
          getResearch(),
          getSiteContent(),
          getPaperSamples().catch(() => []),
        ]).then(([publications, people, research, content, samples]) => ({
          publications,
          people,
          research,
          content,
          samples,
        }));
    load
      .then((d) => alive && setData(d))
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

  if (IS_SAMPLES) {
    return (
      <main>
        <Samples samples={data.samples} publications={data.publications} />
      </main>
    );
  }

  const content = data.content;
  const meta = content.site_meta || {};

  const proseSection = (key) => {
    const v = content[key];
    if (!v || !v.text) return null;
    return (
      <div className="prose-block" key={key}>
        <h2>{PROSE_TITLES[key]}</h2>
        <Prose text={v.text} />
      </div>
    );
  };

  return (
    <main>
      <Header meta={meta} />

      <div className="two-col">
        {proseSection("vision")}
        {proseSection("innovation")}
      </div>

      <h2>People</h2>
      <People people={data.people} onPersonClick={(name) => {
        setAuthorFilter(name);
        setTimeout(() => {
          const el = document.getElementById("publications");
          if (el) el.scrollIntoView({ behavior: "smooth" });
        }, 50);
      }} />

      <h2>Research</h2>
      <Research projects={data.research} />
      <div className="note">
        For past projects, see our old HCT site{" "}
        <a href="https://hct.ece.ubc.ca/research">research page</a>.
      </div>
      <SamplesCallout samples={data.samples} />

      {proseSection("contact")}
      {proseSection("land_acknowledgment")}
      {proseSection("edi")}
      {proseSection("sponsors")}
      {proseSection("opportunities")}

      <h2 className="section" id="publications">
        Publications
      </h2>
      <Publications publications={data.publications} authorFilter={authorFilter} onClearAuthor={() => setAuthorFilter(null)} />

      <footer>
        Copyright {new Date().getFullYear()} © Human Communication Technologies Lab.
      </footer>
    </main>
  );
}
