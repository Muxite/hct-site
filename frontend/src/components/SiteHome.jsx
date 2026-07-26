import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../variants.css";
import {
  getPublicationsPage,
  getTimeline,
  getPeople,
  getProjects,
  getSiteContent,
  updateSiteContent,
  updateProject,
} from "../data/db.js";
import { uploadToSiteMedia } from "../data/storage.js";
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
  shouldReloadGalleryData,
} from "../lib/variants.js";
import { groupByYear, formatAuthors, typeLabel } from "../lib/format.js";
import { splitByKind, emailLabel, assetUrl, projectImagePath } from "../lib/format.js";
import { useAdmin } from "../context/AdminContext.jsx";
import {
  PEOPLE_KIND_SYNC_CAVEAT,
  ADD_PERSON_SYNC_CAVEAT,
  addPersonWithPhoto,
  usePersonEditor,
  useAddPersonForm,
} from "../hooks/usePersonEditor.js";
import CommandPalette from "./CommandPalette.jsx";
import Header from "./Header.jsx";
import Home from "./Home.jsx";
import Prose from "./Prose.jsx";
import EditableText from "./EditableText.jsx";
import EditableImage from "./EditableImage.jsx";
import { splitSections } from "../lib/sections.js";
import "../admin.css";

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
  const { editMode } = useAdmin();

  const isClassic = variant === "classic";

  // Classic (<Home>) writes straight to Supabase via its own db.js calls
  // (Home.jsx/People.jsx) and always refetches fresh on mount, since it's a
  // genuinely separate component that mounts/unmounts each time `isClassic`
  // flips. Gallery's `data` below is different: it's fetched once and cached
  // for the lifetime of this SiteHome instance (deliberately — see the next
  // effect's own comment), so an edit made in Classic would otherwise stay
  // invisible in Gallery after toggling back, until a hard reload.
  //
  // `reloadToken` closes that gap for the one case worth paying an extra
  // Supabase round trip for: an admin toggling from Classic back to a
  // redesign while actively editing (`editMode`). A plain visitor flipping
  // looks back and forth never bumps this, so the original "fetch once,
  // cache" behavior/cost is unchanged for everyone else. `wasClassicRef`
  // remembers *last render's* `isClassic` so the bump only fires on the
  // actual Classic -> redesign transition, not on every render while
  // `editMode` happens to be true.
  const [reloadToken, setReloadToken] = useState(0);
  const wasClassicRef = useRef(isClassic);
  useEffect(() => {
    const wasClassic = wasClassicRef.current;
    wasClassicRef.current = isClassic;
    if (shouldReloadGalleryData({ wasClassic, isClassic, editMode })) {
      setReloadToken((n) => n + 1);
    }
  }, [isClassic, editMode]);

  // The heavy record fetch (1000 pubs + timeline) only feeds the themed
  // redesigns — Classic renders <Home>, which does its own lighter fetch. So we
  // lazily load the gallery data the first time a redesign is selected and
  // cache it thereafter — except `reloadToken` (see above) forces one more
  // fetch when an editing admin returns from Classic, since they may have
  // just edited a person/project/prose section there.
  //
  // `data` is deliberately *not* in the dependency array even though the
  // body reads it: this effect must only re-run on an `isClassic`/
  // `reloadToken` transition, never merely because `data` itself changed —
  // and it changes on every in-place edit made *within* Gallery too (see
  // updatePeopleList/updateProjectsList/saveContent below), each of which
  // calls `onDataChange`/`setData`. Depending on `data` here would refetch
  // the whole record after every single Gallery edit once `reloadToken` had
  // ever been bumped past 0 in this session — wasteful, and a race against
  // that same edit's own optimistic local update.
  useEffect(() => {
    if (isClassic) return;
    if (data && reloadToken === 0) return;
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
  }, [isClassic, reloadToken]);

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
          <Gallery data={data} onDataChange={setData} />
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

// One themed prose section — the same site_content row + the same
// EditableText/updateSiteContent wiring Home.jsx's own `proseSection` uses
// (see saveContent in Gallery below), just rendered inside vlab's own
// heading/section markup. Renders nothing when the key is missing from
// site_content *and* no admin is editing, so a partial database degrades
// quietly instead of showing an empty heading; an admin in edit mode instead
// gets the heading plus an empty EditableText to add the section's first text
// (mirrors Home.jsx's Task 7 addition — same behavior, same site_content
// key, different theme's markup).
function VlabProse({ content, sectionKey, title, editable = false, onSave }) {
  const value = content?.[sectionKey];
  const text = value?.text || "";
  if (!text && !editable) return null;
  return (
    <section className="vlab-section" id={`vlab-${sectionKey}`}>
      <h2 className="vlab-h2">{title || VLAB_PROSE_TITLES[sectionKey]}</h2>
      <EditableText
        value={text}
        editable={editable}
        multiline
        placeholder="Add text for this section…"
        render={(t) => (t ? <Prose text={t} /> : null)}
        onSave={onSave}
      />
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
//
// Editing: same site_content key ("opportunities") and the same raw-markdown
// round trip Home.jsx's proseSection uses — EditableText's read mode renders
// the accordion (via `renderBody` below), its edit mode swaps to a plain
// textarea over the *whole* raw text (sub-headings included), same as Home.jsx.
// Saving re-parses the new text on the next render, so adding/renaming a
// "## Heading" line immediately changes the accordion's own sections.
function renderOpportunitiesBody(text) {
  if (!text) return null;
  const { introText, sections } = splitSections(text);
  if (!sections.length) return <Prose text={text} />;
  return (
    <>
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
    </>
  );
}

function VlabOpportunities({ content, editable = false, onSave }) {
  const value = content?.opportunities;
  const text = value?.text || "";
  if (!text && !editable) return null;

  return (
    <section className="vlab-section" id="vlab-opportunities">
      <h2 className="vlab-h2">Opportunities</h2>
      <EditableText
        value={text}
        editable={editable}
        multiline
        placeholder="Add text for this section…"
        render={renderOpportunitiesBody}
        onSave={onSave}
      />
    </section>
  );
}

// --- the themed homepage ----------------------------------------------------
function Gallery({ data, onDataChange }) {
  const { publications, pubTotal, timeline, people, projects, content } = data;
  const meta = content.site_meta || {};
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;

  // Persists one site_content row, then folds the same value into `data` (owned
  // by SiteHome, passed down as `onDataChange`) so the read view reflects it
  // without a full refetch — same shape as Home.jsx's own `saveContent`, just
  // updating the parent's `data.content` instead of a local one (Gallery
  // doesn't own its data the way Home.jsx does; SiteHome fetches it once and
  // hands it down to whichever look is active).
  const saveContent = useCallback(
    async (key, nextText) => {
      const fallbackTitle = key === "opportunities" ? "Opportunities" : VLAB_PROSE_TITLES[key];
      const nextValue = { ...(content[key] || { title: fallbackTitle }), text: nextText };
      await updateSiteContent(key, nextValue);
      onDataChange((d) => ({ ...d, content: { ...d.content, [key]: nextValue } }));
    },
    [content, onDataChange],
  );

  // Same fold-back shape for the people/projects tables — Roster/ProjectGrid
  // do the actual insert/update/delete (reusing db.js's People-CRUD calls),
  // then report the resulting list back up here.
  const updatePeopleList = useCallback(
    (updater) => onDataChange((d) => ({ ...d, people: updater(d.people) })),
    [onDataChange],
  );
  const updateProjectsList = useCallback(
    (updater) => onDataChange((d) => ({ ...d, projects: updater(d.projects) })),
    [onDataChange],
  );

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
        <VlabProse content={content} sectionKey="vision" editable={editable} onSave={(t) => saveContent("vision", t)} />
        <VlabProse content={content} sectionKey="innovation" editable={editable} onSave={(t) => saveContent("innovation", t)} />
        <VlabOpportunities content={content} editable={editable} onSave={(t) => saveContent("opportunities", t)} />
        <VlabProse content={content} sectionKey="sponsors" editable={editable} onSave={(t) => saveContent("sponsors", t)} />
        <VlabProse content={content} sectionKey="edi" editable={editable} onSave={(t) => saveContent("edi", t)} />
        <VlabProse content={content} sectionKey="land_acknowledgment" editable={editable} onSave={(t) => saveContent("land_acknowledgment", t)} />
        <VlabProse content={content} sectionKey="contact" editable={editable} onSave={(t) => saveContent("contact", t)} />
      </>
    ),
    // `saveContent`'s own identity only changes when `content`/`onDataChange`
    // do (see its useCallback above) — not on every keystroke in the search
    // box — so this still only re-parses the markdown when the underlying
    // content or the admin's edit-mode actually changes, matching the
    // original comment's intent.
    [content, editable, saveContent],
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
        <Roster people={people} onPeopleChange={updatePeopleList} />
      </section>

      {/* PROJECTS — only the current ones; past projects are one click away */}
      <section className="vlab-section" id="vlab-projects">
        <h2 className="vlab-h2">Projects</h2>
        <ProjectGrid projects={featuredProjects} onProjectsChange={updateProjectsList} />
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

// Roster (+ PersonCard/AddPersonCard below) is Gallery's own equivalent of
// People.jsx — same roster table, same insertPerson/updatePerson/deletePerson/
// uploadToSiteMedia calls, same photoPath convention, same role/email/bio/kind
// field set and people.kind sync caveat, all shared via hooks/usePersonEditor.js
// — but its own vlab-* card markup, so wiring People.jsx in wholesale here
// would mean two visually incompatible tile designs sitting side by side
// inside one themed page (see task-8-report.md for why this shape was chosen
// over rendering <People> directly).
function Roster({ people, onPeopleChange }) {
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;
  const [current, alumni] = splitByKind(people, "alumni");

  function handleSaved(next) {
    onPeopleChange((prev) => prev.map((p) => (p.name === next.name ? { ...p, ...next } : p)));
  }
  function handleDeleted(name) {
    onPeopleChange((prev) => prev.filter((p) => p.name !== name));
  }
  async function handleAdd(fields, file) {
    const created = await addPersonWithPhoto(fields, file, people);
    onPeopleChange((prev) => [...prev, created]);
  }

  return (
    <>
      <div className="vlab-people">
        {current.map((p) => (
          <PersonCard key={p.name} person={p} editable={editable} onSaved={handleSaved} onDeleted={handleDeleted} />
        ))}
      </div>
      {alumni.length > 0 && (
        <>
          <h3 className="vlab-sub">Alumni</h3>
          <div className="vlab-people vlab-people--alumni">
            {alumni.map((p) => (
              <PersonCard key={p.name} person={p} editable={editable} onSaved={handleSaved} onDeleted={handleDeleted} />
            ))}
          </div>
        </>
      )}
      {editable && <AddPersonCard onAdd={handleAdd} />}
    </>
  );
}

function PersonCard({ person, editable = false, onSaved, onDeleted }) {
  const {
    editing,
    draft,
    setDraft,
    status,
    errorMsg,
    startEdit,
    cancel,
    handleSave,
    handleDelete,
    handlePhotoSave,
  } = usePersonEditor(person, { onSaved, onDeleted });

  const photo = person.photo ? assetUrl(person.photo) : PHOTO_FALLBACK;

  return (
    <div className="vlab-person">
      {editable ? (
        <EditableImage
          value={person.photo}
          onSave={handlePhotoSave}
          editable
          alt={person.name}
          fallback={PHOTO_FALLBACK}
        />
      ) : (
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
      )}
      <div className="vlab-person__info">
        {/* `name` is immutable here too — see People.jsx/db.js's
            people_name_key comment; there is deliberately no name field in
            this edit form. */}
        <strong className="vlab-person__name">{person.name}</strong>

        {!editing ? (
          <>
            {person.role && <span className="vlab-person__role">{person.role}</span>}
            {person.email && (
              <a className="vlab-person__email" href={`mailto:${person.email}`}>{emailLabel(person.email)}</a>
            )}
            {editable && (
              <div className="admin-person-actions">
                <button type="button" className="admin-btn" onClick={startEdit}>
                  Edit
                </button>
                <button
                  type="button"
                  className="admin-btn"
                  onClick={handleDelete}
                  disabled={status === "saving"}
                >
                  {status === "saving" ? "Removing…" : "Remove"}
                </button>
              </div>
            )}
            {status === "error" && (
              <p className="editable-text__error" role="alert">
                {errorMsg}
              </p>
            )}
          </>
        ) : (
          <form className="admin-person-form" onSubmit={handleSave}>
            <label>
              Role
              <input
                type="text"
                value={draft.role}
                onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={draft.email}
                onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Bio
              <textarea
                rows={3}
                value={draft.bio}
                onChange={(e) => setDraft((d) => ({ ...d, bio: e.target.value }))}
                disabled={status === "saving"}
              />
            </label>
            <label>
              Status
              <select
                value={draft.kind}
                onChange={(e) => setDraft((d) => ({ ...d, kind: e.target.value }))}
                disabled={status === "saving"}
              >
                <option value="current">Current</option>
                <option value="alumni">Alumni</option>
              </select>
            </label>
            {/* Same coordination caveat as People.jsx's PersonTile (Task 7) —
                both edit the same `people` row, so the same sync-revert risk
                applies here. Single-sourced in hooks/usePersonEditor.js. */}
            <p className="admin-caption">{PEOPLE_KIND_SYNC_CAVEAT}</p>
            <div className="editable-text__actions">
              <button
                type="button"
                className="admin-btn"
                onClick={cancel}
                disabled={status === "saving"}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="admin-btn admin-btn--primary"
                disabled={status === "saving"}
              >
                {status === "saving" ? "Saving…" : "Save"}
              </button>
            </div>
            {status === "error" && (
              <p className="editable-text__error" role="alert">
                Couldn't save — {errorMsg}
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}

// Same shape as People.jsx's AddPersonForm (name/role/email/photo/status,
// name immutable once created), styled to sit below the vlab-people grid
// rather than the Classic roster.
function AddPersonCard({ onAdd }) {
  const { fields, setField, status, errorMsg, handleFileChange, handleSubmit } = useAddPersonForm(onAdd);
  const saving = status === "saving";

  return (
    <form className="admin-person-form admin-add-person" onSubmit={handleSubmit}>
      <h4>Add person</h4>
      <label>
        Name
        <input
          type="text"
          value={fields.name}
          onChange={(e) => setField("name", e.target.value)}
          required
          disabled={saving}
        />
      </label>
      <label>
        Role
        <input
          type="text"
          value={fields.role}
          onChange={(e) => setField("role", e.target.value)}
          disabled={saving}
        />
      </label>
      <label>
        Email
        <input
          type="email"
          value={fields.email}
          onChange={(e) => setField("email", e.target.value)}
          disabled={saving}
        />
      </label>
      <label>
        Photo
        <input type="file" accept="image/*" onChange={handleFileChange} disabled={saving} />
      </label>
      <label>
        Status
        <select
          value={fields.kind}
          onChange={(e) => setField("kind", e.target.value)}
          disabled={saving}
        >
          <option value="current">Current</option>
          <option value="alumni">Alumni</option>
        </select>
      </label>
      <p className="admin-caption">{ADD_PERSON_SYNC_CAVEAT}</p>
      <div className="editable-text__actions">
        <button
          type="submit"
          className="admin-btn admin-btn--primary"
          disabled={!fields.name.trim() || saving}
        >
          {saving ? "Adding…" : "Add person"}
        </button>
      </div>
      {status === "error" && (
        <p className="editable-text__error" role="alert">
          Couldn't add — {errorMsg}
        </p>
      )}
    </form>
  );
}

function ProjectGrid({ projects, onProjectsChange }) {
  const { isAdmin, editMode } = useAdmin();
  const editable = isAdmin && editMode;
  const [current, archived] = splitByKind(projects, "archived");

  function handleSaved(next) {
    onProjectsChange((prev) => prev.map((p) => (p.slug && p.slug === next.slug ? { ...p, ...next } : p)));
  }

  return (
    <div className="vlab-projects">
      {[...current, ...archived].map((pr) => (
        <ProjectCard key={pr.slug || pr.title} project={pr} editable={editable} onSaved={handleSaved} />
      ))}
    </div>
  );
}

// A project without a `slug` predates the project-page restructure (see
// docs/PROJECTS.md) and has no stable key `updateProject`/uploadToSiteMedia's
// path convention can target — same "identity must exist before it's
// editable" rule as PersonCard's immutable `name`, just for a missing field
// instead of a locked one. Such a project renders exactly as before: no edit
// affordance, no project-page link either (nothing has changed for it).
function ProjectCard({ project: pr, editable, onSaved }) {
  const blurb = pr.tagline || pr.description || "";
  const image = pr.hero_image || pr.image;
  const canEditImage = editable && Boolean(pr.slug);

  async function handleImageSave(file) {
    if (!pr.slug) return;
    const url = await uploadToSiteMedia(file, projectImagePath(pr.slug, file));
    const saved = await updateProject(pr.slug, { hero_image: url });
    onSaved(saved || { ...pr, hero_image: url });
  }

  const body = (
    <div className="vlab-project__body">
      <h3 className="vlab-project__title">{pr.title}</h3>
      {blurb && <p className="vlab-project__blurb">{blurb}</p>}
      {pr.slug &&
        (canEditImage ? (
          // The card itself can't be the whole-tile <a> in edit mode (see
          // below) — this is the one remaining way to reach the project page.
          <a className="vlab-project__go" href={`#/projects/${pr.slug}`}>Open project →</a>
        ) : (
          <span className="vlab-project__go">Open project →</span>
        ))}
    </div>
  );

  const media = (image || canEditImage) && (
    <div className={`vlab-project__img${canEditImage ? " vlab-project__img--editing" : ""}`}>
      {canEditImage ? (
        <EditableImage value={image} onSave={handleImageSave} editable alt={pr.title} />
      ) : (
        image && (
          <img
            alt={pr.title}
            src={assetUrl(image)}
            loading="lazy"
            onError={(e) => {
              const w = e.currentTarget.closest(".vlab-project__img");
              if (w) w.style.display = "none";
            }}
          />
        )
      )}
    </div>
  );

  // Read mode (and any project missing a slug) keeps the original "the whole
  // card is a link" design. Edit mode can't: EditableImage renders its own
  // Choose-file/Save/Cancel <button>s, and a <button> nested inside an <a>
  // is both invalid HTML and would hijack every click as a navigation (the
  // click bubbles to the anchor before the button's own handler settles
  // anything useful) — so in edit mode the tile becomes a plain <div> with
  // the "Open project →" text above promoted to its own real link instead.
  if (canEditImage) {
    return (
      <div className="vlab-project">
        {media}
        {body}
      </div>
    );
  }

  const inner = (
    <>
      {media}
      {body}
    </>
  );
  return pr.slug ? (
    <a className="vlab-project" href={`#/projects/${pr.slug}`}>{inner}</a>
  ) : (
    <div className="vlab-project">{inner}</div>
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
