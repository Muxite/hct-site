import { useEffect, useState } from "react";
import {
  getTimeline,
  getPeople,
  getResearch,
  getSiteContent,
} from "./data/db.js";
import { useRoute } from "./lib/useRoute.js";
import Header from "./components/Header.jsx";
import Section from "./components/Section.jsx";
import Timeline from "./components/Timeline.jsx";
import People from "./components/People.jsx";
import Research from "./components/Research.jsx";
import PaperDetail from "./components/PaperDetail.jsx";

// The site is data-driven: timeline (full publication history), people, research,
// and the prose sections all come from Supabase, which the backend fills from the
// CV + the editable YAMLs. Everything loads in one pass on mount.
export default function App() {
  const { paper, navigate } = useRoute();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getTimeline(), getPeople(), getResearch(), getSiteContent()])
      .then(([timeline, people, research, content]) => {
        if (alive) setData({ timeline, people, research, content });
      })
      .catch((err) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return (
      <div className="state state--error">
        <p>Couldn’t reach the lab database.</p>
        <code>{String(error.message || error)}</code>
      </div>
    );
  }
  if (!data) {
    return <div className="state state--loading">Loading…</div>;
  }

  const meta = data.content.site_meta || {};
  const navItems = Array.isArray(meta.nav) ? meta.nav : [];

  if (paper) {
    return <PaperDetail slug={paper} meta={meta} onBack={() => navigate(null)} />;
  }

  return (
    <>
      <Header meta={meta} nav={navItems} />
      <main className="content">
        <Section id="latest" title="Latest" eyebrow="01">
          <Timeline entries={data.timeline} onSelect={navigate} />
        </Section>

        <ProseSection id="vision" content={data.content.vision} eyebrow="02" />
        <ProseSection id="innovation" content={data.content.innovation} eyebrow="03" />

        <Section id="people" title="People" eyebrow="04">
          <People people={data.people} />
        </Section>

        <Section id="research" title="Research" eyebrow="05">
          <Research projects={data.research} />
        </Section>

        <ProseSection id="contact" content={data.content.contact} eyebrow="06" />
        <ProseSection id="opportunities" content={data.content.opportunities} eyebrow="07" />
        <ProseSection id="sponsors" content={data.content.sponsors} eyebrow="08" />
        <ProseSection id="edi" content={data.content.edi} eyebrow="09" />
        <ProseSection
          id="land_acknowledgment"
          content={data.content.land_acknowledgment}
          eyebrow="10"
        />
      </main>
      <footer className="footer">
        <span>{meta.subtitle || meta.title || "HCT Lab"}</span>
        <span>University of British Columbia</span>
      </footer>
    </>
  );
}

// A prose section is only rendered when its site_content key exists.
function ProseSection({ id, content, eyebrow }) {
  if (!content || !content.text) return null;
  return (
    <Section id={id} title={content.title} eyebrow={eyebrow}>
      <Section.Prose text={content.text} />
    </Section>
  );
}
