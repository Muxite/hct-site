import { useEffect, useMemo, useRef, useState } from "react";
import "../variants.css";
import {
  getPublicationsPage,
  getTimeline,
  getPeople,
  getProjects,
  getSiteContent,
} from "../data/db.js";
import {
  THEMES,
  DEFAULT_THEME,
  isTheme,
  themeById,
  yearHistogram,
  buildStats,
  filterPublications,
  pubTypes,
  buildCommandIndex,
  PEOPLE_SECTION_ID,
} from "../lib/variants.js";
import { groupByYear, formatAuthors, typeLabel } from "../lib/format.js";
import { splitByKind, emailLabel, assetUrl } from "../lib/format.js";
import CommandPalette from "./CommandPalette.jsx";
import Header from "./Header.jsx";
import Home from "./Home.jsx";
import Prose from "./Prose.jsx";
import { splitSections } from "../lib/sections.js";

const THEME_KEY = "hct-variant";
const MODE_KEY = "hct-variant-mode";
const PHOTO_FALLBACK = "/Human Communication Technologies Lab_files/person.png";
const RENDER_CAP = 80; // how many filtered pubs to render before "load more"

// Signal is now the default look, so first-time visitors land on the modern
// redesign; Classic — the real, content-complete master site (prose + people
// + projects + the paginated publication list) — remains fully available one
// click away via the top selector. Nothing about Classic's own content or
// behavior changes; only which look loads first.

// The lab homepage. A single sticky selector at the top switches the site
// between four looks. "Classic" renders the genuine master homepage (with all
// its prose sections); the other three re-render the record — hero, the
// publication "spectrogram", live search, people, projects — inside a themed
// shell. Every feature (search, the clickable timeline, dark mode, ⌘K) works
// identically in each redesign; only the paint changes. All content is live
// Supabase data — nothing here is invented.
export default function SiteHome({ meta = {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [variant, setVariant] = useState(() => readStored(THEME_KEY, DEFAULT_THEME, isTheme));
  const [dark, setDark] = useState(() => readStored(MODE_KEY, "light") === "dark");

  const isClassic = variant === "classic";

  // The heavy record fetch (1000 pubs + timeline) only feeds the themed
  // redesigns — Classic renders <Home>, which does its own lighter fetch. So we
  // lazily load the gallery data the first time a redesign is selected and
  // cache it thereafter.
  useEffect(() => {
    if (isClassic || data) return;
    let alive = true;
    Promise.all([
      getPublicationsPage({ offset: 0, limit: 1000 }),
      getTimeline(),
      getPeople(),
      getProjects(),
      getSiteContent(),
    ])
      .then(([pubs, timeline, people, projects, content]) => ({
        publications: pubs.rows,
        pubTotal: pubs.total,
        timeline,
        people,
        projects,
        content,
      }))
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, [isClassic, data]);

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_KEY, variant);
      window.localStorage.setItem(MODE_KEY, dark ? "dark" : "light");
    } catch {
      /* private mode — ignore */
    }
  }, [variant, dark]);

  const theme = themeById(variant);
  // Console is inherently dark; Journal/Classic are inherently light. Only
  // Signal honours the toggle — so `mode` is derived, not just the raw state.
  const mode = variant === "console" ? "dark" : theme.dark && dark ? "dark" : "light";

  const switcher = (
    <Switcher
      variant={variant}
      onVariant={setVariant}
      dark={dark}
      onDark={setDark}
      supportsDark={theme.dark && variant !== "console"}
    />
  );

  // Classic = the untouched master site: shared masthead + the full <Home>
  // (prose sections and all), inside the normal centred <main>.
  if (isClassic) {
    return (
      <div className="vlab-gallery">
        {switcher}
        <main>
          <Header meta={meta} />
          <Home />
          <footer>
            Copyright {new Date().getFullYear()} © Human Communication
            Technologies Lab.
          </footer>
        </main>
      </div>
    );
  }

  if (error) {
    return (
      <div className="vlab-gallery">
        {switcher}
        <div className="state state--error">
          Couldn’t load the redesign — {String(error.message || error)}.{" "}
          <button className="vlab-clear" onClick={() => setVariant("classic")}>
            Back to the classic site.
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="vlab-gallery">
      {switcher}
      {!data ? (
        <div className="state">Loading the lab record…</div>
      ) : (
        <div className="vlab" data-variant={variant} data-mode={mode}>
          <Gallery data={data} />
        </div>
      )}
    </div>
  );
}

// --- the site-look selector (sticky, above everything) ----------------------
function Switcher({ variant, onVariant, dark, onDark, supportsDark }) {
  return (
    <div className="vlab-switch">
      <div className="vlab-switch__lead">
        <span className="vlab-switch__tag">Site look</span>
      </div>
      <div className="vlab-switch__tabs" role="tablist" aria-label="Site look">
        {THEMES.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={variant === t.id}
            className={`vlab-switch__tab${variant === t.id ? " is-on" : ""}`}
            onClick={() => onVariant(t.id)}
            title={t.blurb}
          >
            {t.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="vlab-switch__mode"
        onClick={() => onDark(!dark)}
        disabled={!supportsDark}
        title={supportsDark ? "Toggle light / dark" : "This look sets its own mode"}
      >
        {dark ? "◐ Dark" : "◑ Light"}
      </button>
    </div>
  );
}

// The prose the legacy site carried — the same site_content keys Classic
// renders via <Home>. Order here is deliberate: the record and the people come
// first (this redesign's centerpiece), then what the lab is for, who funds it,
// what it stands for, and how to reach it.
const VLAB_PROSE_TITLES = {
  vision: "Vision",
  innovation: "Innovation",
  sponsors: "Sponsors",
  edi: "Equity, Diversity, Inclusion + Indigeneity",
  land_acknowledgment: "Land Acknowledgment",
  contact: "Contact",
};

// One themed prose section. Renders nothing when the key is missing from
// site_content, so a partial database degrades quietly instead of showing an
// empty heading.
function VlabProse({ content, sectionKey, title }) {
  const value = content?.[sectionKey];
  if (!value || !value.text) return null;
  return (
    <section className="vlab-section" id={`vlab-${sectionKey}`}>
      <h2 className="vlab-h2">{title || VLAB_PROSE_TITLES[sectionKey]}</h2>
      <Prose text={value.text} />
    </section>
  );
}

// Opportunities is five audience-specific asks (undergrads, PhD/Master, RAs,
// post-docs, visitors) — 3 KB of prose in which every reader wants exactly one
// paragraph. Native <details> panels: keyboard-accessible, no dependency, and
// they honour prefers-reduced-motion for free. If the content ever loses its
// sub-headings, `sections` comes back empty and this falls through to the same
// flat prose Classic shows — completeness is the requirement, the accordion is
// polish.
function VlabOpportunities({ content }) {
  const value = content?.opportunities;
  if (!value || !value.text) return null;
  const { introText, sections } = splitSections(value.text);
  if (!sections.length) return <VlabProse content={content} sectionKey="opportunities" title="Opportunities" />;

  return (
    <section className="vlab-section" id="vlab-opportunities">
      <h2 className="vlab-h2">Opportunities</h2>
      {introText && <Prose text={introText} />}
      <div className="vlab-acc">
        {sections.map((s, i) => (
          <details className="vlab-acc__item" key={s.title} open={i === 0}>
            <summary className="vlab-acc__head">
              <span className="vlab-acc__title">{s.title}</span>
              <span className="vlab-acc__mark" aria-hidden="true" />
            </summary>
            <div className="vlab-acc__body">
              <Prose text={s.text} />
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

// --- the themed homepage ----------------------------------------------------
function Gallery({ data }) {
  const { publications, pubTotal, timeline, people, projects, content } = data;
  const meta = content.site_meta || {};

  const [query, setQuery] = useState("");
  const [year, setYear] = useState(null);
  const [type, setType] = useState(null);
  const [limit, setLimit] = useState(RENDER_CAP);
  const pubsRef = useRef(null);

  const hist = useMemo(() => yearHistogram(timeline), [timeline]);
  const stats = useMemo(
    () => buildStats({ pubTotal, timeline, people, projects }),
    [pubTotal, timeline, people, projects],
  );
  const types = useMemo(() => pubTypes(publications), [publications]);
  // Featured = current status; the rest (past/archived projects) only show
  // up when you click through to the full projects page.
  const [featuredProjects, archivedProjectsList] = useMemo(
    () => splitByKind(projects, "archived"),
    [projects],
  );
  const archivedCount = archivedProjectsList.length;
  const cmdIndex = useMemo(
    () => buildCommandIndex({ publications, people, projects }),
    [publications, people, projects],
  );

  const filtered = useMemo(
    () => filterPublications(publications, { query, year, type }),
    [publications, query, year, type],
  );
  useEffect(() => setLimit(RENDER_CAP), [query, year, type]);

  // ⌘K hits that have no page of their own (people) navigate to this page with
  // `?to=<section id>`. The router drops the query string, so the link resolves
  // to the homepage route; the scroll is ours to do. A plain "#…" fragment
  // can't be used — the URL's one hash already belongs to the router.
  useEffect(() => {
    const jump = () => {
      const q = window.location.hash.split("?")[1];
      const to = q && new URLSearchParams(q).get("to");
      if (to) document.getElementById(to)?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    jump();
    window.addEventListener("hashchange", jump);
    return () => window.removeEventListener("hashchange", jump);
  }, []);

  const maxCount = hist.reduce((m, d) => Math.max(m, d.count), 0) || 1;
  const active = Boolean(query || year || type);

  // The seven prose sections re-parse their markdown on every render, and the
  // search box's state lives up here — so without this every keystroke re-ran
  // splitSections + a dozen parseMarkdown passes over ~10 KB of text that
  // cannot have changed. `content` is fetched once and never mutated, so this
  // memo effectively runs the parse a single time.
  const prose = useMemo(
    () => (
      <>
        <VlabProse content={content} sectionKey="vision" />
        <VlabProse content={content} sectionKey="innovation" />
        <VlabOpportunities content={content} />
        <VlabProse content={content} sectionKey="sponsors" />
        <VlabProse content={content} sectionKey="edi" />
        <VlabProse content={content} sectionKey="land_acknowledgment" />
        <VlabProse content={content} sectionKey="contact" />
      </>
    ),
    [content],
  );

  const pickYear = (y) => {
    setYear((cur) => (cur === y ? null : y));
    // jump to the results so the filter's effect is visible
    requestAnimationFrame(() => pubsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const clearAll = () => {
    setQuery("");
    setYear(null);
    setType(null);
  };

  const shown = filtered.slice(0, limit);
  const groups = groupByYear(shown);

  return (
    <>
      <CommandPalette index={cmdIndex} />

      {/* HERO — the lab's 43-year publication cadence as a spectrogram */}
      <header className="vlab-hero">
        {/* Two-column on wide viewports: the lab's name reads left, the record's
            headline numbers sit right. Collapses to one column under 760px. */}
        <div className="vlab-hero__top">
          <div className="vlab-hero__lead">
            <p className="vlab-hero__eyebrow">
              UBC · Electrical &amp; Computer Engineering · est. {stats.firstYear}
            </p>
            <h1 className="vlab-hero__title">{meta.subtitle || "Human Communication Technologies Lab"}</h1>
            <p className="vlab-hero__tagline">{meta.tagline}</p>
          </div>

          <dl className="vlab-stats">
            <Stat n={stats.publications} label="publications" />
            <Stat n={stats.years} label="years active" />
            <Stat n={stats.people} label="lab members" />
            <Stat n={stats.projects} label="active projects" />
            <Stat n={stats.peakYear} label={`peak year · ${stats.peakCount} papers`} plain />
          </dl>
        </div>

        <figure className="vlab-spectro" aria-label="Publications per year since first record">
          <div className="vlab-spectro__bars">
            {hist.map((d) => {
              const on = year === d.year;
              const dim = year != null && !on;
              return (
                <button
                  key={d.year}
                  className={`vlab-spectro__bar${on ? " is-on" : ""}${dim ? " is-dim" : ""}`}
                  style={{ "--h": `${Math.max(2, Math.round((d.count / maxCount) * 100))}%` }}
                  onClick={() => pickYear(d.year)}
                  title={`${d.year}: ${d.count} publication${d.count === 1 ? "" : "s"}`}
                  aria-label={`${d.year}, ${d.count} publications${on ? " (filtering)" : ""}`}
                />
              );
            })}
          </div>
          <figcaption className="vlab-spectro__axis">
            <span>{stats.firstYear}</span>
            <span className="vlab-spectro__hint">
              {year ? `Filtering ${year} — click again to clear` : "Each bar is a year — click to filter the record"}
            </span>
            <span>{stats.lastYear}</span>
          </figcaption>
        </figure>
      </header>

      {/* SEARCH + FILTER over the full record */}
      <section className="vlab-find" ref={pubsRef}>
        <div className="vlab-find__head">
          <h2 className="vlab-h2">The record</h2>
          <p className="vlab-find__count">
            {active ? (
              <>
                <strong>{filtered.length}</strong> of {publications.length} ·{" "}
                <button className="vlab-clear" onClick={clearAll}>clear filters</button>
              </>
            ) : (
              <>
                <strong>{publications.length}</strong> publications, 1983–{stats.lastYear} ·{" "}
                <a href="#/papers">browse as a plain list →</a>
              </>
            )}
          </p>
        </div>
        <div className="vlab-search">
          <span className="vlab-search__icon" aria-hidden="true">⌕</span>
          <input
            className="vlab-search__input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, authors, venues…"
            aria-label="Search publications"
            spellCheck="false"
          />
          {query && (
            <button className="vlab-search__clear" onClick={() => setQuery("")} aria-label="Clear search">×</button>
          )}
        </div>
        <div className="vlab-chips" role="group" aria-label="Filter by type">
          <button className={`vlab-chip${!type ? " is-on" : ""}`} onClick={() => setType(null)}>All</button>
          {types.map((t) => (
            <button
              key={t}
              className={`vlab-chip${type === t ? " is-on" : ""}`}
              onClick={() => setType((cur) => (cur === t ? null : t))}
            >
              {typeLabel(t)}
            </button>
          ))}
          {year != null && (
            <button className="vlab-chip vlab-chip--year is-on" onClick={() => setYear(null)}>
              {year} ×
            </button>
          )}
        </div>

        <div className="vlab-pubs">
          {filtered.length === 0 ? (
            <p className="vlab-empty">No publications match. <button className="vlab-clear" onClick={clearAll}>Reset</button></p>
          ) : (
            groups.map(([y, items]) => (
              <div className="vlab-pubyear" key={y}>
                <h3 className="vlab-pubyear__label">{y}</h3>
                <ol className="vlab-pubyear__list">
                  {items.map((p, i) => (
                    <PubRow key={p.slug || `${y}-${i}`} pub={p} />
                  ))}
                </ol>
              </div>
            ))
          )}
          {filtered.length > limit && (
            <button className="vlab-more" onClick={() => setLimit((l) => l + RENDER_CAP)}>
              Show more — {limit} of {filtered.length}
            </button>
          )}
        </div>
      </section>

      {/* PEOPLE */}
      <section className="vlab-section" id={PEOPLE_SECTION_ID}>
        <h2 className="vlab-h2">People</h2>
        <Roster people={people} />
      </section>

      {/* PROJECTS — only the current ones; past projects are one click away */}
      <section className="vlab-section" id="vlab-projects">
        <h2 className="vlab-h2">Projects</h2>
        <ProjectGrid projects={featuredProjects} />
        {archivedCount > 0 && (
          <a className="vlab-more" href="#/projects">
            See all {projects.length} projects — including {archivedCount} past projects →
          </a>
        )}
      </section>

      {/* The prose the legacy site carried — live site_content, nothing invented */}
      {prose}

      <footer className="vlab-foot">
        <span>
          © {new Date().getFullYear()} {meta.title || "HCT Lab"}
        </span>
        <span className="vlab-foot__hint">Switch the site look at the top ↑</span>
      </footer>
    </>
  );
}

// The term precedes its description, as a description list requires — screen
// readers announce them in DOM order. `.vlab-stat` is column-reverse so the
// number still reads above its label.
function Stat({ n, label, plain }) {
  return (
    <div className="vlab-stat">
      <dt className="vlab-stat__label">{label}</dt>
      <dd className="vlab-stat__n">{plain ? n ?? "—" : (n ?? 0).toLocaleString()}</dd>
    </div>
  );
}

function PubRow({ pub }) {
  const [showBib, setShowBib] = useState(false);
  return (
    <li className="vlab-pub">
      <a
        className="vlab-pub__title"
        href={pub.slug ? `#/papers/${pub.slug}` : pub.link || "#/"}
      >
        {pub.title}
      </a>
      <div className="vlab-pub__meta">
        <span className="vlab-pub__authors">{formatAuthors(pub.authors)}</span>
        {pub.venue && <span className="vlab-pub__venue"> · {pub.venue}</span>}
        <span className="vlab-pub__type">{typeLabel(pub.type)}</span>
      </div>
      <div className="vlab-pub__links">
        {pub.link && (
          <a href={pub.link} target="_blank" rel="noreferrer">source ↗</a>
        )}
        {pub.bibtex && (
          <button className="vlab-pub__bibtoggle" onClick={() => setShowBib((v) => !v)}>
            {showBib ? "hide bibtex" : "bibtex"}
          </button>
        )}
      </div>
      {pub.bibtex && showBib && <pre className="vlab-pub__bibtex">{pub.bibtex}</pre>}
    </li>
  );
}

function Roster({ people }) {
  const [current, alumni] = splitByKind(people, "alumni");
  return (
    <>
      <div className="vlab-people">
        {current.map((p) => <PersonCard key={p.name} person={p} />)}
      </div>
      {alumni.length > 0 && (
        <>
          <h3 className="vlab-sub">Alumni</h3>
          <div className="vlab-people vlab-people--alumni">
            {alumni.map((p) => <PersonCard key={p.name} person={p} />)}
          </div>
        </>
      )}
    </>
  );
}

function PersonCard({ person }) {
  const photo = person.photo ? assetUrl(person.photo) : PHOTO_FALLBACK;
  return (
    <div className="vlab-person">
      <img
        className="vlab-person__photo"
        alt={person.name}
        src={photo}
        loading="lazy"
        onError={(e) => {
          e.currentTarget.onerror = null;
          e.currentTarget.src = PHOTO_FALLBACK;
        }}
      />
      <div className="vlab-person__info">
        <strong className="vlab-person__name">{person.name}</strong>
        {person.role && <span className="vlab-person__role">{person.role}</span>}
        {person.email && (
          <a className="vlab-person__email" href={`mailto:${person.email}`}>{emailLabel(person.email)}</a>
        )}
      </div>
    </div>
  );
}

function ProjectGrid({ projects }) {
  const [current, archived] = splitByKind(projects, "archived");
  return (
    <div className="vlab-projects">
      {[...current, ...archived].map((pr) => {
        const blurb = pr.tagline || pr.description || "";
        const image = pr.hero_image || pr.image;
        const inner = (
          <>
            {image && (
              <div className="vlab-project__img">
                <img
                  alt={pr.title}
                  src={assetUrl(image)}
                  loading="lazy"
                  onError={(e) => {
                    const w = e.currentTarget.closest(".vlab-project__img");
                    if (w) w.style.display = "none";
                  }}
                />
              </div>
            )}
            <div className="vlab-project__body">
              <h3 className="vlab-project__title">{pr.title}</h3>
              {blurb && <p className="vlab-project__blurb">{blurb}</p>}
              {pr.slug && <span className="vlab-project__go">Open project →</span>}
            </div>
          </>
        );
        return pr.slug ? (
          <a className="vlab-project" key={pr.slug} href={`#/projects/${pr.slug}`}>{inner}</a>
        ) : (
          <div className="vlab-project" key={pr.title}>{inner}</div>
        );
      })}
    </div>
  );
}

function readStored(key, fallback, valid) {
  try {
    const v = window.localStorage.getItem(key);
    if (v && (!valid || valid(v))) return v;
  } catch {
    /* ignore */
  }
  return fallback;
}
