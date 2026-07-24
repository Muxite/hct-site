# Modernized, content-complete HCT site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three modern looks (Signal / Console / Journal) show everything the legacy HCT site showed — vision, values, sponsors, opportunities, people, all 65 projects, the full record — and fix the two confirmed visual bugs, without touching Classic.

**Architecture:** Three independent slices. (1) CSS-only fixes in `variants.css` that stop the global `styles.css` element rules from leaking paint into the gallery's semantic `<header>`. (2) New prose sections inside the existing `Gallery()` in `SiteHome.jsx`, rendered by the already-tested `Prose.jsx` / `lib/prose.js`, themed with the existing `--v-*` tokens. (3) A deterministic, credential-free snapshot builder in the Python backend that turns `projects.yaml` into the `research` + `project_people` arrays of `frontend/src/data/snapshot.json`, so all 65 projects render offline.

**Tech Stack:** React 18 + Vite 5 (no new deps), plain CSS custom properties, `node --test` for pure JS helpers, Python 3 + Pydantic + `pytest` for the backend.

**Source spec:** `docs/superpowers/specs/2026-07-24-modernized-hct-site-design.md`

## Global Constraints

- **Branch:** `feat/variants-gallery`. It already carries ~1,435 uncommitted lines (the 65-project `projects.yaml`, `PapersPage`, `ProjectsPage`, `Feedback`). Do **not** revert or stash them; commit only the files each task names.
- **No new dependencies.** Not in `frontend/package.json`, not in `backend/pyproject.toml`.
- **No live network, no LLM calls, no Supabase writes** in any code or test. Repo-root `.env` has `SB_SEC_KEY=` and `OPENROUTER_API_KEY=` empty; the work must not need them.
- **Classic is untouched.** No edits to `Home.jsx`, `Prose.jsx`, `lib/prose.js`'s existing exports, or any `.prose` rule in `styles.css`. Classic already renders every prose section; this plan only brings the other three looks up to parity.
- **Frontend tests are pure-helper only** (`npm test` → `node --test`, no DOM, no React renderer). Logic that needs a test goes in `src/lib/*.js` with a sibling `*.test.js`. Component and CSS behavior is verified in the browser instead (see "Browser verification" below).
- **Backend tests:** `cd backend && PYTHONPATH=. pytest`. The package imports as `src`.
- **Baseline is green** — verified 2026-07-24: `npm test` → 60 pass / 0 fail. Any task that ends red is not done.
- **Commit after every task** with the repo's message style (imperative subject, a short body explaining *why*), ending with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
  ```

### Browser verification (used by Tasks 1, 2, 4, 5)

Several tasks are verified by reading **computed styles in a real browser** — that is the red/green cycle for CSS. Setup, once:

```bash
cd frontend && VITE_MOCK=1 npm run dev   # serves http://localhost:5173 with no Supabase keys
```

Then drive it with the Playwright MCP tools: `browser_navigate` → `browser_evaluate`.
Switch look by clicking the "Console" / "Signal" / "Journal" tab in the sticky
selector, or by seeding storage before load:

```js
// browser_evaluate, then reload
() => { localStorage.setItem("hct-variant", "console"); }
```

**Known environment failure:** Playwright MCP previously died with
`Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome`.
If that recurs, run `npx playwright install chrome` once, or fall back to a
headless check that needs no MCP:

```bash
cd frontend && npx playwright install chromium   # once, if needed
```

If no browser can be installed at all, the fallback is a manual screenshot by
the user; **do not** mark a CSS task verified on inspection of the source alone.

### Two corrections to the spec (verified against the code — trust these, not the spec)

1. **The prose sub-headings are `###`, not `##`.** The spec's Workstream 2 says
   `opportunities` is "four audience sub-sections, each an `##` heading". Checked
   against `snapshot.json`: `opportunities` has **five** `###` sub-sections
   (Undergraduate Students / PhD and Master Students / Undergraduate Research
   Assistantships and Part-time RA / Post-Docs and Research Associates /
   Associates and Visiting Researchers) and `sponsors` has an intro paragraph
   plus **three** `###` groups (Industry and Not-for-Profits / Government /
   University). `parseMarkdown` yields these as `{type:"heading", level:3}`.
   Task 3's splitter therefore keys on the heading blocks it actually finds, not
   on a hardcoded level.
2. **The snapshot builder lives at `backend/src/snapshot.py`, not
   `backend/scripts/build_snapshot.py`.** There is no `backend/scripts/`
   directory, and `python -m` needs an importable package. `src/snapshot.py`
   matches the repo convention (`CLAUDE.md`: "Package is imported as `src`",
   "Every Python module has unit tests") and is runnable as
   `python -m src.snapshot`.

---

### Task 1: Stop the global masthead rule painting over the gallery hero

The confirmed Console bug. `styles.css:86` styles the bare element `header`
(the Classic sticky masthead) with a translucent white background + blur +
bottom hairline. `.vlab-hero` is a semantic `<header>`, so it inherits that
paint. On the three light looks it is white-on-white (invisible); on Console's
near-black `--v-bg: #0a0c10` it paints a light-gray slab under the near-white
title, which is why the hero title looks like it's missing.

`variants.css:90` already resets the *layout* leak (`display`, `margin`) and
`styles.css:99` (`.vlab-gallery header { position: static }`) already kills the
`position: sticky` leak. Only the paint properties are left.

**Files:**
- Modify: `frontend/src/variants.css:87-94`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. Later tasks rely on `.vlab-hero` having a
  transparent background.

- [ ] **Step 1: Write the failing check**

Start the dev server (see "Browser verification"), navigate to
`http://localhost:5173/`, switch to the **Console** look, then run this in
`browser_evaluate`:

```js
() => {
  const h = document.querySelector(".vlab-hero");
  const s = getComputedStyle(h);
  return {
    background: s.backgroundColor,
    backdrop: s.backdropFilter || s.webkitBackdropFilter,
    borderBottom: s.borderBottomWidth,
    // is the title actually the topmost thing at its own centre?
    topmostAtTitle: (() => {
      const t = document.querySelector(".vlab-hero__title").getBoundingClientRect();
      const el = document.elementFromPoint(t.left + 8, t.top + t.height / 2);
      return el && el.className;
    })(),
  };
}
```

- [ ] **Step 2: Run it and record the failure**

Expected (buggy) result: `background: "rgba(255, 255, 255, 0.85)"`,
`backdrop: "blur(8px)"`, `borderBottom: "1px"`. Save this output — it is the
"before" evidence.

- [ ] **Step 3: Apply the reset**

In `frontend/src/variants.css`, replace the existing rule at line 90:

```css
.vlab header, .vlab footer { display: block; margin: 0; }
```

with:

```css
/* Layout leaks (display/margin) *and* paint leaks. styles.css:86 styles the
   bare element `header` for Classic's sticky masthead — translucent white,
   blurred, hairline bottom. `.vlab-hero` is a semantic <header>, so on the
   light looks that slab is white-on-white (invisible) and on Console's
   near-black background it paints a light slab under the title. `position:
   sticky` is already neutralized by `.vlab-gallery header` in styles.css:99.
   Note: no `padding` reset here — the global rules set none, and a `.vlab
   header` padding declaration (0,1,1) would out-specify `.vlab-hero` (0,1,0)
   and flatten the hero. */
.vlab header, .vlab footer {
  display: block;
  margin: 0;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-bottom: 0;
}
```

- [ ] **Step 4: Re-run the check in all four looks**

Reload and re-run the Step 1 snippet for `console`, `signal`, `journal`.
Expected in each: `background: "rgba(0, 0, 0, 0)"`, `backdrop: "none"`,
`borderBottom: "0px"`, and `topmostAtTitle` containing `vlab-hero__title`.

Then click through to **Classic** and confirm its masthead still has the
translucent sticky bar:

```js
() => {
  const s = getComputedStyle(document.querySelector(".vlab-gallery main header"));
  return { background: s.backgroundColor, backdrop: s.backdropFilter };
}
```
Expected: still `rgba(255, 255, 255, 0.85)` / `blur(8px)` — Classic unchanged.

- [ ] **Step 5: Commit**

```bash
cd /home/muk/projects/hct-site
git add frontend/src/variants.css
git commit -m "$(cat <<'EOF'
Stop the global masthead rule painting over the gallery hero

`.vlab-hero` is a semantic <header>, so styles.css's bare `header` rule (the
Classic sticky masthead: translucent white + blur + hairline) leaked its paint
into every redesign. Invisible on the light looks; on Console's near-black
background it painted a light slab under the hero title, which read as the
title being missing. The existing reset only covered layout (display/margin).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 2: Rebalance the hero into two columns

The hero is heavily left-weighted (title capped at `16ch`, tagline at `46ch`)
with a large empty right column on wide viewports. Move the stat block beside
the title on wide screens; it collapses back under the existing 760px
breakpoint. Spectrogram stays full-width beneath — it is the signature element.

**Files:**
- Modify: `frontend/src/components/SiteHome.jsx:243-283` (regroup hero children)
- Modify: `frontend/src/variants.css:96-151` (hero grid) and `:413-420` (responsive)

**Interfaces:**
- Consumes: `.vlab-hero`'s transparent background from Task 1.
- Produces: new class names `.vlab-hero__top`, `.vlab-hero__lead` used only
  inside `SiteHome.jsx` and `variants.css`.

- [ ] **Step 1: Write the failing check**

With the dev server running on the **Signal** look, `browser_evaluate`:

```js
() => {
  const top = document.querySelector(".vlab-hero__top");
  return {
    exists: Boolean(top),
    cols: top && getComputedStyle(top).gridTemplateColumns,
    statsAfterSpectro: (() => {
      const kids = [...document.querySelector(".vlab-hero").children].map((n) => n.className);
      return kids;
    })(),
  };
}
```

- [ ] **Step 2: Run it and record the failure**

Expected: `exists: false`, and the children list is
`["vlab-hero__eyebrow", "vlab-hero__title", "vlab-hero__tagline", "vlab-spectro", "vlab-stats"]`
— one column, stats stranded at the bottom.

- [ ] **Step 3: Regroup the hero JSX**

In `frontend/src/components/SiteHome.jsx`, the hero currently reads
eyebrow → title → tagline → `<figure class="vlab-spectro">` → `<dl class="vlab-stats">`.
Wrap the eyebrow/title/tagline in a `.vlab-hero__lead` div and pull the
existing `<dl className="vlab-stats">` up beside it inside a new
`.vlab-hero__top` grid. Replace lines 243-283 with:

```jsx
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
```

- [ ] **Step 4: Add the grid CSS**

In `frontend/src/variants.css`, immediately after the `.vlab-hero` rule
(line 97), add:

```css
/* Wide viewports: name on the left, the record's headline numbers on the right,
   so the hero reads as intentional rather than half-drawn. The 1.4fr/1fr split
   keeps the title's 16ch measure intact. */
.vlab-hero__top {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: clamp(24px, 5vw, 72px);
  align-items: end;
}
.vlab-hero__lead { min-width: 0; }
```

Then change the `.vlab-stats` rule (line 137) from a 5-across row into a
2-across block that sits in the hero's right column:

```css
.vlab-stats {
  display: grid; grid-template-columns: repeat(2, 1fr);
  gap: clamp(12px, 2vw, 28px) clamp(16px, 3vw, 36px); margin: 0;
  padding: 0; border-top: 1px solid var(--v-line); padding-top: 22px;
}
.vlab-stat:last-child { grid-column: span 2; }
```

And in the `@media (max-width: 760px)` block (line 413), replace the two
`.vlab-stats` / `.vlab-stat:last-child` lines with:

```css
  .vlab-hero__top { grid-template-columns: 1fr; gap: 32px; align-items: start; }
  .vlab-stats { row-gap: 24px; }
```

- [ ] **Step 5: Re-run the check at two widths**

Re-run the Step 1 snippet at a wide viewport (`browser_resize` to 1440×900).
Expected: `exists: true`, `cols` is two non-zero px values, and the hero's
children are `["vlab-hero__top", "vlab-spectro"]`.

Then `browser_resize` to 600×900 and re-run. Expected: `cols` is a **single**
px value (collapsed).

Confirm the stats still read correctly (five entries, last spanning) and that
the spectrogram bars still filter on click in both Signal and Console.

- [ ] **Step 6: Commit**

```bash
cd /home/muk/projects/hct-site
git add frontend/src/components/SiteHome.jsx frontend/src/variants.css
git commit -m "$(cat <<'EOF'
Balance the modern hero into two columns

The hero was heavily left-weighted — a 16ch title and 46ch tagline against a
large empty right column. The stat block now sits beside the lab name on wide
viewports (2x2 + a spanning peak-year row) and collapses back under the
existing 760px breakpoint. The spectrogram stays full-bleed beneath it; it is
the signature element.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 3: `splitSections` — a pure helper that cuts prose into heading groups

`opportunities` (five `###` audience groups) and `sponsors` (an intro paragraph
plus three `###` groups) both need to be split into an intro and a list of
titled groups — for the accordion in Task 5 and for grouped rendering in
Task 4. This is pure array logic over `parseMarkdown`'s output, so it is
unit-testable under `node --test`; the component work in Tasks 4-5 is not.

**Files:**
- Create: `frontend/src/lib/sections.js`
- Create: `frontend/src/lib/sections.test.js`

**Interfaces:**
- Consumes: `parseMarkdown(text)` from `../lib/prose.js`, which returns a flat
  array of blocks — `{type:"heading", level:number, inline:Node[]}`,
  `{type:"paragraph", inline:Node[]}`, `{type:"list", ordered:boolean, items:[]}`.
- Produces:
  ```js
  splitSections(text) -> {
    intro: Block[],          // blocks before the first heading
    introText: string,       // the same span as raw markdown
    sections: Array<{ title: string, blocks: Block[], text: string }>,
  }
  ```
  `intro` is every block before the first heading (empty array when the text
  starts with one). Each section's `title` is the heading's plain text; its
  `blocks` are the blocks up to the next heading **at the same or shallower
  level**, and its `text` is that same span as **raw markdown, heading line
  excluded** — `Prose` takes a string, so returning the slice here keeps the
  heading-scanning logic in one tested place instead of re-deriving it in a
  component. Task 5 imports `splitSections` by this exact name; Task 4 does
  not use it.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/sections.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";

import { splitSections } from "./sections.js";

test("splitSections returns leading blocks as intro", () => {
  const { intro, sections } = splitSections("Grateful to our sponsors.\n\n### Government\n\nNSERC / CIHR");
  assert.equal(intro.length, 1);
  assert.equal(intro[0].type, "paragraph");
  assert.equal(sections.length, 1);
  assert.equal(sections[0].title, "Government");
});

test("splitSections groups blocks under their heading", () => {
  const text = [
    "### Undergraduate Students",
    "",
    "Check the capstone page.",
    "",
    "### PhD and Master Students",
    "",
    "Always looking for excellent students.",
    "",
    "- a required letter",
    "- a transcript",
  ].join("\n");
  const { intro, sections } = splitSections(text);
  assert.equal(intro.length, 0);
  assert.deepEqual(sections.map((s) => s.title), [
    "Undergraduate Students",
    "PhD and Master Students",
  ]);
  assert.equal(sections[0].blocks.length, 1);
  assert.equal(sections[1].blocks.length, 2);
  assert.equal(sections[1].blocks[1].type, "list");
});

test("splitSections keeps a deeper heading inside its parent section", () => {
  const { sections } = splitSections("## Group\n\nlead\n\n### Sub\n\ndetail\n\n## Other\n\ntail");
  assert.deepEqual(sections.map((s) => s.title), ["Group", "Other"]);
  // the deeper "### Sub" heading stays as a block inside "Group"
  assert.equal(sections[0].blocks.length, 3);
  assert.equal(sections[0].blocks[1].type, "heading");
});

test("splitSections flattens bold and links in a heading title", () => {
  const { sections } = splitSections("### **Post-Docs** and [Visitors](https://example.com)\n\nx");
  assert.equal(sections[0].title, "Post-Docs and Visitors");
});

test("splitSections returns each section's raw markdown without its heading", () => {
  const text = "### Government\n\nNSERC / CIHR\n\n### University\n\nUBC";
  const { sections } = splitSections(text);
  assert.equal(sections[0].text, "NSERC / CIHR");
  assert.equal(sections[1].text, "UBC");
  // the heading line itself is never part of the body
  assert.ok(!sections[0].text.includes("###"));
});

test("splitSections returns the lead paragraph as introText", () => {
  const { introText } = splitSections("Grateful to our sponsors.\n\n### Government\n\nNSERC");
  assert.equal(introText, "Grateful to our sponsors.");
  // a "#" inside a URL must not be mistaken for a heading
  const { introText: t2 } = splitSections("See https://x.test/a#frag here.\n\n### G\n\nn");
  assert.equal(t2, "See https://x.test/a#frag here.");
});

test("splitSections tolerates empty and headingless text", () => {
  assert.deepEqual(splitSections(""), { intro: [], introText: "", sections: [] });
  const flat = splitSections("Just a paragraph.");
  assert.equal(flat.sections.length, 0);
  assert.equal(flat.intro.length, 1);
  assert.equal(flat.introText, "Just a paragraph.");
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './sections.js'`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/sections.js`:

```js
/**
 * Cut a Markdown-subset site_content block into an intro plus heading-titled
 * sections. `sponsors` and `opportunities` are authored as an optional lead
 * paragraph followed by "###" groups (Industry / Government / University;
 * Undergraduate / PhD / RA / Post-Doc / Visiting), and the modern looks render
 * those groups as separate units — a collapsible panel each, or a titled block.
 *
 * The split level is whatever the *first* heading uses, so this works whether
 * the content is authored with "##" or "###". A deeper heading is left in place
 * as an ordinary block inside its parent section.
 *
 * Each section carries both its parsed `blocks` and its raw markdown `text`.
 * <Prose> takes a string, so returning the slice here keeps heading-scanning in
 * one tested place instead of re-deriving it inside a component.
 *
 * Pure (no React/DOM) so it is unit-testable.
 */
import { parseMarkdown } from "./prose.js";

// The same heading shape parseMarkdown recognizes — the line scan below and the
// block list must agree on what counts as a heading or the slices would drift.
const HEADING_LINE = /^\s*(#{1,4})\s+(.+?)\s*$/;

/** Flatten an inline node array to plain text (drops bold/link markup). */
export function inlineText(nodes) {
  return (nodes || [])
    .map((n) => {
      if (n.t === "text") return n.v;
      if (n.t === "break") return " ";
      if (n.t === "bold" || n.t === "link") return inlineText(n.children);
      return "";
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitSections(text) {
  const src = String(text ?? "").replace(/\r/g, "");
  const blocks = parseMarkdown(src);
  const first = blocks.find((b) => b.type === "heading");
  if (!first) return { intro: blocks, introText: src.trim(), sections: [] };

  const level = first.level;
  const lines = src.split("\n");
  const slice = (from, to) => lines.slice(from, to).join("\n").trim();
  // Where each split-level heading starts, so a section's raw text is the span
  // between its heading line and the next one.
  const cuts = [];
  lines.forEach((line, i) => {
    const m = HEADING_LINE.exec(line);
    if (m && m[1].length <= level) cuts.push(i);
  });

  const intro = [];
  const sections = [];
  for (const b of blocks) {
    if (b.type === "heading" && b.level <= level) {
      sections.push({ title: inlineText(b.inline), blocks: [], text: "" });
      continue;
    }
    (sections.length ? sections[sections.length - 1].blocks : intro).push(b);
  }
  // cuts and sections are produced by the same predicate, so they align 1:1.
  sections.forEach((s, i) => {
    s.text = slice(cuts[i] + 1, i + 1 < cuts.length ? cuts[i + 1] : lines.length);
  });

  return { intro, introText: slice(0, cuts[0]), sections };
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test`
Expected: PASS — 67 tests total (60 baseline + 7 new), 0 fail.

- [ ] **Step 5: Commit**

```bash
cd /home/muk/projects/hct-site
git add frontend/src/lib/sections.js frontend/src/lib/sections.test.js
git commit -m "$(cat <<'EOF'
Add splitSections: cut prose blocks into heading groups

sponsors and opportunities are authored as an optional lead paragraph plus
"###" groups. The modern looks need those groups as separate units (a
collapsible panel each), so split them once, in a pure helper, rather than
re-deriving the structure in JSX. The split level follows the first heading,
so "##"-authored content works the same way.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 4: Render the missing prose sections in the modern looks

`Gallery()` already fetches `content` (all eight `site_content` keys) and never
renders seven of them. Add them, themed with the `--v-*` tokens, reusing
`Prose.jsx`. New section order:

```
hero → The record → People → Projects → Vision → Innovation
     → Sponsors → EDII → Land Acknowledgment → Contact → footer
```

(The spec put Vision/Innovation directly under the hero. Keep them **after**
the record instead: the record is this redesign's centerpiece and the hero
already carries the lab's tagline — moving prose above the fold would push the
spectrogram down and undercut the "technical feel" the user asked to keep.
Everything the spec listed still renders; only the order differs, and it now
matches Classic's own order — record-adjacent content first, values last.)

**Files:**
- Modify: `frontend/src/components/SiteHome.jsx` (import `Prose`, add
  `VlabProse`, add sections to `Gallery()` before `<footer className="vlab-foot">`)
- Modify: `frontend/src/variants.css` (append a `.vlab .prose` block before the
  THEME sections at line ~328)

**Interfaces:**
- Consumes: `Prose` from `./Prose.jsx` and the `content` object already
  destructured in `Gallery()` (`content[key]` → `{ text: string }` or
  undefined). This task does **not** use `splitSections` — Task 5 does.
- Produces: `VlabProse` and `VLAB_PROSE_TITLES` inside `SiteHome.jsx`; Task 5
  replaces `VlabProse`'s use for the `opportunities` key only.

- [ ] **Step 1: Write the failing check**

Dev server on **Signal**, `browser_evaluate`:

```js
() => [...document.querySelectorAll(".vlab-h2")].map((h) => h.textContent.trim())
```

- [ ] **Step 2: Run it and record the failure**

Expected (incomplete): `["The record", "People", "Projects"]` — the seven prose
sections are absent.

- [ ] **Step 3: Add the section titles and the `VlabProse` component**

In `frontend/src/components/SiteHome.jsx`, add to the imports at the top
(after the `Home` import on line 25):

```jsx
import Prose from "./Prose.jsx";
```

Then, just above `function Gallery({ data })` (line 187), add:

```jsx
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
```

- [ ] **Step 4: Render the sections in `Gallery()`**

In `Gallery()`, replace the closing `<footer className="vlab-foot">` block
(currently lines 375-380) with the prose sections followed by that same footer:

```jsx
      {/* The prose the legacy site carried — live site_content, nothing invented */}
      <VlabProse content={content} sectionKey="vision" />
      <VlabProse content={content} sectionKey="innovation" />
      <VlabProse content={content} sectionKey="opportunities" title="Opportunities" />
      <VlabProse content={content} sectionKey="sponsors" />
      <VlabProse content={content} sectionKey="edi" />
      <VlabProse content={content} sectionKey="land_acknowledgment" />
      <VlabProse content={content} sectionKey="contact" />

      <footer className="vlab-foot">
        <span>
          © {new Date().getFullYear()} {meta.title || "HCT Lab"}
        </span>
        <span className="vlab-foot__hint">Switch the site look at the top ↑</span>
      </footer>
```

(`opportunities` renders as plain prose for now; Task 5 turns it into the
accordion. Passing `title` explicitly keeps it out of `VLAB_PROSE_TITLES`,
which Task 5's component reads.)

- [ ] **Step 5: Theme the prose under `.vlab`**

`styles.css` styles `.prose` for Classic with a hardcoded `#1155cc` link blue
and a bold-italic sub-heading. Both look wrong on Console and Journal. Append
this to `frontend/src/variants.css`, immediately before the
`THEME: Signal` banner comment (line ~328):

```css
/* --- prose sections (site_content) ---------------------------------------- */
/* Prose.jsx emits the same .prose markup Classic uses, so styles.css's rules
   apply here too — including a hardcoded #1155cc link blue and a bold-italic
   sub-heading. Re-bind them to the active look's tokens. Descendant selectors
   here are 0,2,0 and beat styles.css's 0,1,0 .prose rules. */
.vlab .prose {
  max-width: 68ch;
  margin-top: 18px;
  color: var(--v-muted);
  line-height: 1.62;
  font-size: 15.5px;
}
.vlab .prose a { color: var(--v-accent-2); text-decoration: underline; text-underline-offset: 2px; }
.vlab .prose a:hover { color: var(--v-accent); }
.vlab .prose strong { color: var(--v-ink); font-weight: 600; }
.vlab .prose__heading {
  font-family: var(--v-font-display);
  font-style: normal; font-weight: 600; font-size: 1rem;
  color: var(--v-ink); margin: 1.6em 0 .5em;
}
.vlab .prose li { margin: .3em 0; }
.vlab .prose ul, .vlab .prose ol { padding-left: 1.4em; }

/* Console labels its sub-headings like the section headers; Journal keeps the
   scholarly italic it uses everywhere else. */
.vlab[data-variant="console"] .prose__heading::before { content: "> "; color: var(--v-accent-2); }
.vlab[data-variant="journal"] .prose__heading { font-style: italic; font-weight: 500; }
```

- [ ] **Step 6: Re-run the check in all three modern looks**

Re-run the Step 1 snippet. Expected in each of Signal / Console / Journal:

```
["The record", "People", "Projects", "Vision", "Innovation",
 "Opportunities", "Sponsors", "Equity, Diversity, Inclusion + Indigeneity",
 "Land Acknowledgment", "Contact"]
```

Then confirm the links picked up the theme (not Classic's blue):

```js
() => getComputedStyle(document.querySelector("#vlab-contact .prose a")).color
```
Expected on Console: `rgb(70, 211, 160)` (`--v-accent-2`), **not** `rgb(17, 85, 204)`.

Finally, click to **Classic** and confirm its prose is unchanged — link colour
should still be `rgb(17, 85, 204)`:

```js
() => getComputedStyle(document.querySelector(".prose-block .prose a")).color
```

- [ ] **Step 7: Run the unit tests**

Run: `cd frontend && npm test`
Expected: PASS, 67 tests (unchanged — this task adds no pure helpers).

- [ ] **Step 8: Commit**

```bash
cd /home/muk/projects/hct-site
git add frontend/src/components/SiteHome.jsx frontend/src/variants.css
git commit -m "$(cat <<'EOF'
Render every site_content section in the modern looks

Signal / Console / Journal rendered hero -> record -> people -> projects and
dropped the seven prose sections the legacy site carried, even though Gallery
already fetched them. Vision, Innovation, Opportunities, Sponsors, EDII, Land
Acknowledgment and Contact now render after the record, themed with the --v-*
tokens and reusing the tested Prose parser. .prose is rebound under .vlab so
links and sub-headings follow the active look instead of Classic's fixed blue.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 5: Turn Opportunities into a native accordion

`opportunities` is 3 KB of five audience-specific asks. Rendered flat it is the
longest block on the page and buries the one paragraph any given reader wants.
Split it into `<details>` panels — native, keyboard-accessible, no dependency,
and it degrades to plain prose if the split finds nothing.

**Files:**
- Modify: `frontend/src/components/SiteHome.jsx` (add `VlabOpportunities`,
  swap it in for the `opportunities` `VlabProse`)
- Modify: `frontend/src/variants.css` (append accordion rules after the
  `.vlab .prose` block from Task 4)

**Interfaces:**
- Consumes: `splitSections(text) -> { intro, sections }` from
  `../lib/sections.js` (Task 3), and `Prose` from `./Prose.jsx`.
- Produces: `VlabOpportunities` — internal to `SiteHome.jsx`.

- [ ] **Step 1: Write the failing check**

Dev server on **Signal**, `browser_evaluate`:

```js
() => {
  const panels = [...document.querySelectorAll("#vlab-opportunities details")];
  return {
    count: panels.length,
    titles: panels.map((d) => d.querySelector("summary").textContent.trim()),
    firstOpen: panels[0]?.open ?? null,
  };
}
```

- [ ] **Step 2: Run it and record the failure**

Expected: `{ count: 0, titles: [], firstOpen: null }` — Task 4 renders it flat.

- [ ] **Step 3: Add the accordion component**

In `frontend/src/components/SiteHome.jsx`, add to the imports (next to the
`Prose` import from Task 4):

```jsx
import { splitSections } from "../lib/sections.js";
```

Then add, directly below `VlabProse`:

```jsx
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
```

- [ ] **Step 4: Swap it in**

In `Gallery()`, replace the `opportunities` line added in Task 4:

```jsx
      <VlabProse content={content} sectionKey="opportunities" title="Opportunities" />
```

with:

```jsx
      <VlabOpportunities content={content} />
```

- [ ] **Step 5: Add the accordion CSS**

Append to `frontend/src/variants.css`, right after the `.vlab .prose` block
from Task 4:

```css
/* --- accordion (Opportunities) -------------------------------------------- */
.vlab-acc { margin-top: 20px; border-top: 1px solid var(--v-line); }
.vlab-acc__item { border-bottom: 1px solid var(--v-line); }
.vlab-acc__head {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 16px 2px; cursor: pointer; list-style: none;
  font-family: var(--v-font-display); font-size: 1.02rem; font-weight: 600;
  color: var(--v-ink);
}
.vlab-acc__head::-webkit-details-marker { display: none; }
.vlab-acc__head:hover { color: var(--v-accent); }
.vlab-acc__head:focus-visible { outline: 2px solid var(--v-accent); outline-offset: 2px; }
/* A "+" that becomes a "−" when the panel is open — drawn, not a glyph, so it
   stays crisp in every look. */
.vlab-acc__mark { position: relative; width: 14px; height: 14px; flex-shrink: 0; }
.vlab-acc__mark::before, .vlab-acc__mark::after {
  content: ""; position: absolute; background: var(--v-faint);
  transition: transform .18s ease, opacity .18s ease;
}
.vlab-acc__mark::before { inset: 6px 0; height: 2px; }
.vlab-acc__mark::after { inset: 0 6px; width: 2px; }
.vlab-acc__item[open] .vlab-acc__mark::after { transform: scaleY(0); opacity: 0; }
.vlab-acc__item[open] .vlab-acc__head { color: var(--v-accent); }
.vlab-acc__body { padding: 0 0 20px; }
.vlab-acc__body .prose { margin-top: 0; }
.vlab[data-variant="console"] .vlab-acc__head::before { content: "[ ] "; color: var(--v-faint); font-size: 12px; }
.vlab[data-variant="console"] .vlab-acc__item[open] .vlab-acc__head::before { content: "[x] "; color: var(--v-accent); }

@media (prefers-reduced-motion: reduce) {
  .vlab-acc__mark::before, .vlab-acc__mark::after { transition: none; }
}
```

- [ ] **Step 6: Re-run the check**

Re-run the Step 1 snippet. Expected:

```js
{
  count: 5,
  titles: ["Undergraduate Students", "PhD and Master Students",
           "Undergraduate Research Assistantships and Part-time RA",
           "Post-Docs and Research Associates",
           "Associates and Visiting Researchers"],
  firstOpen: true,
}
```

Then confirm a panel's body actually has content and that clicking toggles it:

```js
() => {
  const d = document.querySelectorAll("#vlab-opportunities details")[1];
  d.querySelector("summary").click();
  return { open: d.open, chars: d.querySelector(".vlab-acc__body").textContent.trim().length };
}
```
Expected: `open: true` and `chars` > 100.

Check keyboard access: `browser_press_key` Tab to a summary, then Enter — the
panel must toggle.

- [ ] **Step 7: Run the unit tests**

Run: `cd frontend && npm test`
Expected: PASS, 67 tests.

- [ ] **Step 8: Commit**

```bash
cd /home/muk/projects/hct-site
git add frontend/src/components/SiteHome.jsx frontend/src/variants.css
git commit -m "$(cat <<'EOF'
Collapse Opportunities into per-audience panels

Opportunities is five audience-specific asks and 3 KB of prose — flat, it is
the longest block on the page and buries the one paragraph a given reader
came for. Native <details> panels (no dependency, keyboard-accessible, first
one open) split it by audience. If the content ever loses its sub-headings the
component falls back to the same flat prose Classic renders.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 6: Build `snapshot.json`'s projects from `projects.yaml`

`backend/data/inputs/projects.yaml` holds **65 projects (5 current + 60
archived — verified by running `load_projects_yaml`)**, each archived entry
carrying an LLM-written summary, link and image. `snapshot.json` still has the
old **5** `research` rows, so the offline demo shows no archive and the
homepage teaser ("See all N projects — including M past") is wrong. There is no
snapshot generator in the repo; this adds one.

**Files:**
- Create: `backend/src/snapshot.py`
- Create: `backend/tests/test_snapshot.py`
- Modify: `frontend/src/data/snapshot.json` (regenerated output)

**Interfaces:**
- Consumes: `load_projects_yaml(path) -> (list[ResearchProject], list[ProjectPerson], list[tuple[str,str]])`
  from `src.sync_content`. `ResearchProject` fields: `title, slug, tagline,
  description, summary, link, image, hero_image, kind, sort_order`.
  `ProjectPerson` fields: `project_slug, person_name, role_on_project, sort_order`.
- Produces:
  ```python
  RESEARCH_COLUMNS: tuple[str, ...]          # the columns the frontend reads
  build_snapshot(snapshot: dict, projects, links) -> dict   # pure, no I/O
  write_snapshot(snapshot_path, projects_yaml) -> tuple[int, int]  # (research, project_people)
  ```
  `build_snapshot` is pure so the test needs no files; `write_snapshot` does the
  read/serialize/write. `main(argv)` wires up `python -m src.snapshot`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_snapshot.py`:

```python
"""Unit tests for the offline snapshot builder (no network, no LLM)."""

from __future__ import annotations

import json

from src.models import ProjectPerson, ResearchProject
from src.snapshot import RESEARCH_COLUMNS, build_snapshot, write_snapshot

PROJECTS_YAML = """\
projects:
  - title: Brain2Speech
    tagline: Brain computer interfaces
    link: https://hct.ece.ubc.ca/brain2speech/
    image: ./img/b2s.png
    status: current
    people:
      - name: Prof. Sid Fels
        role: lead
  - title: MyView Multi-View Video
    summary: |
      We built MyView to capture and browse multi-camera video.
    link: https://hct.ece.ubc.ca/project-myview/
    status: archived
"""


def test_build_snapshot_replaces_research_and_keeps_other_tables():
    before = {
        "publications": [{"slug": "p1"}],
        "research": [{"id": "old-uuid", "slug": "gone", "title": "Gone", "kind": "current"}],
        "project_people": [{"project_slug": "gone", "person_name": "X"}],
        "site_content": [{"key": "vision", "value": {"text": "v"}}],
    }
    projects = [
        ResearchProject(title="Brain2Speech", kind="current", sort_order=0).with_slug(),
        ResearchProject(title="MyView", kind="archived", sort_order=1, summary="s").with_slug(),
    ]
    links = [ProjectPerson(project_slug="brain2speech", person_name="Prof. Sid Fels", role_on_project="lead")]

    after = build_snapshot(before, projects, links)

    # untouched tables are preserved verbatim, including key order
    assert after["publications"] == before["publications"]
    assert after["site_content"] == before["site_content"]
    assert list(after) == list(before)
    # research is fully replaced by the YAML rows
    assert [r["slug"] for r in after["research"]] == ["brain2speech", "myview"]
    assert [r["kind"] for r in after["research"]] == ["current", "archived"]
    assert after["project_people"] == [
        {"project_slug": "brain2speech", "person_name": "Prof. Sid Fels", "role_on_project": "lead", "sort_order": 0}
    ]


def test_build_snapshot_emits_exactly_the_columns_the_frontend_reads():
    projects = [ResearchProject(title="Brain2Speech", kind="current").with_slug()]
    after = build_snapshot({"research": [], "project_people": []}, projects, [])
    assert tuple(after["research"][0]) == RESEARCH_COLUMNS
    # no stray Supabase-only column leaks into the offline snapshot
    assert "id" not in after["research"][0]


def test_write_snapshot_round_trips_yaml_to_disk(tmp_path):
    yml = tmp_path / "projects.yaml"
    yml.write_text(PROJECTS_YAML, encoding="utf-8")
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"publications": [], "research": [], "project_people": []}), encoding="utf-8")

    n_research, n_links = write_snapshot(snap, yml)

    assert (n_research, n_links) == (2, 1)
    out = json.loads(snap.read_text(encoding="utf-8"))
    assert [r["title"] for r in out["research"]] == ["Brain2Speech", "MyView Multi-View Video"]
    assert out["research"][1]["summary"].startswith("We built MyView")
    # legible diffs: 2-space indent, trailing newline
    assert snap.read_text(encoding="utf-8").endswith("\n")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.snapshot'`.

- [ ] **Step 3: Write the implementation**

Create `backend/src/snapshot.py`:

```python
"""Rebuild the frontend's offline snapshot's project tables from projects.yaml.

``frontend/src/data/snapshot.json`` is what the site renders in ``VITE_MOCK``
mode — a committed dump of the live Supabase tables so the frontend can be
developed (and demoed) with no keys and no network. Its ``research`` rows went
stale when the 60-project legacy archive landed in ``projects.yaml``.

This is the offline half of the archive rollout; the online half is
``hct-manager sync-content``, which pushes the same YAML to Supabase. Both read
``load_projects_yaml`` so they cannot drift.

Deterministic: local YAML in, local JSON out. No network, no LLM, no keys.

    cd backend && PYTHONPATH=. python -m src.snapshot
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from src.models import ProjectPerson, ResearchProject
from src.sync_content import load_projects_yaml

# Exactly what db.js selects (PROJECT_GRID_COLS + summary for the project page).
# `id` is deliberately absent: the frontend never reads it, and inventing UUIDs
# for 60 offline rows would add churn to every regenerated diff.
RESEARCH_COLUMNS: tuple[str, ...] = (
    "slug",
    "title",
    "tagline",
    "description",
    "summary",
    "link",
    "image",
    "hero_image",
    "kind",
    "sort_order",
)

DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "snapshot.json"
DEFAULT_PROJECTS = Path(__file__).resolve().parents[1] / "data" / "inputs" / "projects.yaml"


def build_snapshot(
    snapshot: dict,
    projects: Iterable[ResearchProject],
    links: Iterable[ProjectPerson],
) -> dict:
    """Return ``snapshot`` with ``research``/``project_people`` rebuilt.

    Every other table is preserved verbatim, and key order is kept so the
    regenerated file diffs cleanly against the committed one.
    """
    out = dict(snapshot)
    out["research"] = [
        {col: getattr(p, col) for col in RESEARCH_COLUMNS} for p in projects
    ]
    out["project_people"] = [link.row() for link in links]
    return out


def write_snapshot(
    snapshot_path: Path | str = DEFAULT_SNAPSHOT,
    projects_yaml: Path | str = DEFAULT_PROJECTS,
) -> tuple[int, int]:
    """Regenerate ``snapshot_path`` from ``projects_yaml``; return row counts."""
    snapshot_path = Path(snapshot_path)
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    projects, links, _membership = load_projects_yaml(projects_yaml)
    updated = build_snapshot(current, projects, links)
    snapshot_path.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return len(updated["research"]), len(updated["project_people"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("--projects", default=str(DEFAULT_PROJECTS))
    args = ap.parse_args(argv)
    n_research, n_links = write_snapshot(args.snapshot, args.projects)
    print(f"snapshot: {n_research} research rows, {n_links} project_people rows")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=. pytest tests/test_snapshot.py -v`
Expected: PASS, 3 tests.

Then the whole backend suite, to prove nothing else moved:
Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS, 0 failures.

- [ ] **Step 5: Regenerate the real snapshot**

Run: `cd backend && PYTHONPATH=. python -m src.snapshot`
Expected stdout: `snapshot: 65 research rows, 5 project_people rows`

Verify the split and that nothing else changed:

```bash
cd /home/muk/projects/hct-site
python3 -c "
import json; d=json.load(open('frontend/src/data/snapshot.json'))
from collections import Counter
print(Counter(r['kind'] for r in d['research']))
print({k: len(v) for k, v in d.items()})"
```
Expected: `Counter({'archived': 60, 'current': 5})` and
`publications: 551, timeline: 526, people: 14, research: 65, site_content: 8,
paper_samples: 8, project_people: 5`.

```bash
git diff --stat frontend/src/data/snapshot.json
```
Expected: only that file, and the diff should be dominated by added `research`
rows. **If `publications` or `timeline` show up in the diff body, stop** — the
builder is rewriting tables it must preserve.

- [ ] **Step 6: Verify in the browser**

With `VITE_MOCK=1 npm run dev` running, on **Signal**:

```js
() => ({
  teaser: document.querySelector(".vlab-section .vlab-more")?.textContent.trim(),
  cards: document.querySelectorAll(".vlab-projects .vlab-project").length,
})
```
Expected: teaser reads `See all 65 projects — including 60 past projects →`
and `cards` is 5 (the homepage shows current only).

Then navigate to `http://localhost:5173/#/projects` and check the archive
renders, and open one archived project page:

```js
() => {
  const links = [...document.querySelectorAll('a[href^="#/projects/"]')];
  return { count: links.length, sample: links[links.length - 1].getAttribute("href") };
}
```
Expected: `count` ≈ 65. Navigate to that `sample` href and confirm the project
page renders a title and its summary paragraph (not an empty state).

- [ ] **Step 7: Commit**

```bash
cd /home/muk/projects/hct-site
git add backend/src/snapshot.py backend/tests/test_snapshot.py frontend/src/data/snapshot.json
git commit -m "$(cat <<'EOF'
Build the offline snapshot's projects from projects.yaml

snapshot.json is what VITE_MOCK mode renders, and its research table still held
the 5 pre-migration rows — so the 60-project legacy archive was invisible
offline and the homepage teaser undercounted. The repo had no snapshot
generator at all; this adds one that reads the same load_projects_yaml the
Supabase sync uses, so the offline and online paths cannot drift. Deterministic
and credential-free: local YAML in, local JSON out.

Regenerated: research 5 -> 65 rows (5 current + 60 archived).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

### Task 7: Document the deploy step and close out the spec

The archive is only half-live after Task 6: offline renders 65 projects,
production still reads the Supabase `research` table, which nobody has pushed
to. That push needs `SB_SEC_KEY` (empty in this repo's `.env`), so it is a
**user-run** step and must be written down rather than silently skipped.

**Files:**
- Modify: `docs/FRONTEND-DB.md` (snapshot regeneration + the deploy step)
- Modify: `docs/LEGACY-SITE-ANALYSIS.md` (mark what this work addressed)
- Modify: `PLANS.md` (status)

**Interfaces:**
- Consumes: the commands verified in Task 6.
- Produces: nothing importable.

- [ ] **Step 1: Read what is there now**

```bash
cd /home/muk/projects/hct-site
grep -n "snapshot" docs/FRONTEND-DB.md
grep -n "^## \|^### " docs/LEGACY-SITE-ANALYSIS.md
```

Do not restructure these docs — add to them where they already discuss the
snapshot and the legacy gaps.

- [ ] **Step 2: Document snapshot regeneration in `docs/FRONTEND-DB.md`**

Add a subsection next to the existing `VITE_MOCK` / snapshot discussion:

```markdown
### Regenerating the offline snapshot

`frontend/src/data/snapshot.json` backs `VITE_MOCK=1` builds. Its `research`
and `project_people` tables are generated from `backend/data/inputs/projects.yaml`
— the same file `hct-manager sync-content` pushes to Supabase, so the offline
and live project lists cannot drift:

```bash
cd backend && PYTHONPATH=. python -m src.snapshot
# -> snapshot: 65 research rows, 5 project_people rows
```

Every other table in the file (publications, timeline, people, site_content,
paper_samples) is preserved verbatim; those are still hand-dumped from Supabase.
```

- [ ] **Step 3: Document the production deploy step in `docs/FRONTEND-DB.md`**

```markdown
### Deploy step — pushing projects to Supabase

The frontend reads projects from the Supabase `research` table, so a snapshot
rebuild alone does **not** change production. After editing `projects.yaml`,
someone with the write key must run:

```bash
# repo root, with SB_SEC_KEY set in .env
docker compose run --rm hct-manager sync-content
# or, with the backend installed locally:
cd backend && PYTHONPATH=. hct-manager sync-content
```

`splitByKind` in the frontend already renders `kind: archived` projects, so no
frontend change is needed once the rows land.
```

- [ ] **Step 4: Mark the addressed items in `docs/LEGACY-SITE-ANALYSIS.md`**

For each gap this work closed, append a short status line in place (do not
delete the analysis — it is the record of what the legacy site had):

- prose sections missing from the modern looks → **Addressed 2026-07-24** —
  Vision, Innovation, Opportunities, Sponsors, EDII, Land Acknowledgment and
  Contact render in Signal/Console/Journal (`SiteHome.jsx`).
- 37-project archive not visible → **Addressed 2026-07-24** — 65 projects
  (5 current + 60 archived) in `projects.yaml`; offline via
  `python -m src.snapshot`, production via `hct-manager sync-content`.
- sponsor **logo grid** → **still open** — blocked on sourcing logo assets.

- [ ] **Step 5: Update `PLANS.md`**

Add to the roadmap/status section:

```markdown
- **2026-07-24 — modernized, content-complete looks.** The three modern looks
  render every `site_content` section (Opportunities as an accordion); the
  gallery hero no longer inherits Classic's masthead paint; `snapshot.json`'s
  projects are generated from `projects.yaml` (65 rows). Plan:
  `docs/superpowers/plans/2026-07-24-modernized-hct-site.md`.
  **Open:** sponsor logo grid (needs assets); `hct-manager sync-content` still
  has to be run with a real `SB_SEC_KEY` to put the archive into production.
```

- [ ] **Step 6: Full verification sweep**

```bash
cd /home/muk/projects/hct-site/frontend && npm test && npm run build
cd ../backend && PYTHONPATH=. pytest -q
```
Expected: 67 frontend tests pass; the Vite build succeeds; the backend suite
passes. Record the actual output — do not claim completion without it.

- [ ] **Step 7: Commit**

```bash
cd /home/muk/projects/hct-site
git add docs/FRONTEND-DB.md docs/LEGACY-SITE-ANALYSIS.md PLANS.md
git commit -m "$(cat <<'EOF'
Document snapshot regeneration and the projects deploy step

The offline snapshot now has a generator and the archive needs a Supabase push
to reach production; both were undocumented. Also marks the legacy-analysis
gaps this work closed, and the one it did not (sponsor logo grid, blocked on
assets).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GFdV3zgRNyNhfEtZmd9yeP
EOF
)"
```

---

## Blocked — needs the user (not part of any task above)

**Workstream 3.2, the production push, cannot be done from an agent session.**
Two independent blockers, both verified on 2026-07-24:

1. **`SB_SEC_KEY` is empty** in the repo-root `.env`. Without the Supabase
   secret key `hct-manager sync-content` cannot write.
2. **The Supabase MCP server routes to the wrong project.** This is the last
   error from the 2026-07-24 08:48 session — `MCP server "supabase" requires
   re-authorization (token expired)` — and it is still unfixed. Two servers
   named `supabase` are registered: the project's `.mcp.json` one, correctly
   pinned to `?project_ref=uashejcjldoedqmgeujc` (HCT) but never approved
   (`enabledMcpjsonServers: []`), and the plugin's `plugin:supabase:supabase`,
   which carries **no** `project_ref` and therefore resolves to the account's
   default project (muksite). Every re-auth landed on muksite because the
   plugin server is the one that was enabled.

   Fix, from a terminal in the project directory:
   ```bash
   cd /home/muk/projects/hct-site
   claude                       # start a session with the project dir as cwd
   /plugin                      # disable the "supabase" plugin
   /mcp                         # approve the project's supabase server, then Authenticate
   ```
   Ground-truth check afterwards: `/mcp` → `supabase` → `get_project_url`
   should return `uashejcjldoedqmgeujc`, not the muksite ref.

   A cleanup script for the three stale muksite credential blocks was staged at
   `/tmp/claude-1000/-home-muk-projects-hct-site/5f251111-.../scratchpad/purge-stale-supabase-creds.py`
   — optional hygiene, and it must only run while Claude Code is fully quit
   (the running app rewrites `.credentials.json` on exit).

Neither blocker affects Tasks 1-7: all of them are offline, and the frontend
needs no change once the rows land in Supabase.

## Non-goals (carried forward from the spec)

- Sponsor **logo grid/carousel** — blocked on sourcing logo image assets.
- **Link-health check** on outbound `research.link` as a `hct-manager qa` extension.
- Reconciling the 270 KB legacy `data/publications.bib` against the CV timeline.
- Active-section scrollspy nav.
- Re-running the migration LLM — already done; `projects.yaml` is the source of truth.
