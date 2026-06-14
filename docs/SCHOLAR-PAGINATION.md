# Scholar pagination + chunked extraction

Status: **implemented** (2026-06-03). ujin shipped the pagination/jobs framework;
hct now plugs into it. Pagination + chunking live in a ujin **job**; extraction +
Supabase writes live in hct **plugins**. Original design notes are kept below.

## How it runs now
- **ujin job** (`backend/jobs/scholar.yaml`): a `plugin:scholar_profile` browser
  source clicks "Show more" (`#gsc_bpf_more`) until the profile is fully loaded,
  harvesting each row (`.gsc_a_tr`) as text → a `chunk` transform (size 20) fans
  the rows out 20-at-a-time → the `plugin:hct_publications` sink.
- **hct plugins** (`backend/ujin_plugins/hct_publications.py`): `scholar_profile`
  (Scholar-specific browser config — keeps selectors out of ujin core) and
  `hct_publications` (per-chunk: `extract_publications` → upsert by slug → rebuild
  timeline), delegating to `src/scholar_ingest.py:ScholarIngestor` (unit-tested).

To run: build the **browser-enabled ujin** (Playwright + Chromium), then
`UJIN_PLUGINS_DIR=…/backend/ujin_plugins PYTHONPATH=…/backend <env> ujin
jobs-serve backend/jobs/scholar.yaml`. Env: `OPENROUTER_API_KEY`, `SB_URL`,
`SB_SEC_KEY`.

**Verify on first real run:** the Scholar selectors (`#gsc_bpf_more`,
`.gsc_a_tr`, `#gsc_a_b`) and that `extract:raw` row text carries authors/venue/
year (the current containers predate the browser build, so this wasn't run live).

---

## Original design notes (deferred phase)

## Problem
Large profiles (Sidney Fels: **200+ papers**) don't fit on one Scholar page.
The page shows the first ~20 rows and a "Show more" button that loads 20 more at
a time. We must (a) get *all* publications, and (b) not feed the whole list to
the LLM at once — too much context hurts extraction accuracy.

## Verified facts (2026-06-03)
- The "Show more" button is just UI for the **`cstart` GET param**. Fetching
  `…&view_op=list_works&sortby=pubdate&cstart=N&pagesize=K` returns the rows
  `[N, N+K)`. Confirmed over plain HTTP: `cstart=0,20,…,200` each return distinct
  ID sets; `cstart=200` still returns 20 → Fels has 200+. So **no DOM clicking is
  required** — pagination is URL-driven.
- `pagesize` alone caps around 100; `cstart` is required for the full set.
- Full per-paper metadata (authors/venue/year) is only in obscura's *rendered
  text*; ujin's `links`/`article` modes drop it (see ARCHITECTURE / scholar.py).

## Decisions
- **Pagination owner: ujin.** hct waits for ujin's native "load all pages"
  capability rather than driving `cstart` itself, since ujin is being rebuilt
  around exactly this.
- **Chunk size: 20 papers per LLM call.** Matches Scholar's native page; smallest
  context → best per-call accuracy. hct chunks regardless of how ujin delivers
  the pages.

## What hct needs from ujin (the ask)
A scrape result for a Scholar profile that returns the **complete** list, ideally
already page-delimited so hct can chunk without re-parsing. Preferred shape:

```jsonc
// POST /scrape  { "url": <profile>, "mode": "scholar_profile" }  (or similar)
{
  "kind": "scholar_profile",
  "pages": [                      // each page = the rendered TEXT of one cstart slice
    "…rendered text of rows 0–19…",
    "…rendered text of rows 20–39…"
  ],
  "page_size": 20,
  "complete": true,               // false if loading stopped early (rate-limited, cap hit)
  "fingerprint": "…"              // stable over the full set for change detection
}
```

Minimum acceptable fallback if `pages[]` isn't feasible: a single `text` field
with the **whole** rendered list (all rows loaded) — hct will split it into
20-row chunks itself (less robust; needs row-boundary detection).

Per page/text, hct needs the table rows only (Scholar's `#gsc_a_b` body) — the
sidebar/co-authors/citation-graph chrome is noise. If ujin can scope the render
to that selector, even better.

## hct-side design (implement when ujin lands)
- `orchestrate`: for a Scholar source, get `pages[]` from ujin, run
  `extract_publications` **once per page** (≤20 papers each → bounded context),
  then merge by stable slug (existing `deduped()`); fingerprint = hash of the
  sorted slug set.
- Stop conditions (only if hct ever has to drive it): short page (`< page_size`),
  no-new-IDs (dedupe guard for clamp-and-repeat), `max_pages` safety cap.
- Partial result rule: never discard everything on a mid-page failure — keep the
  newest pages (they drive the timeline); upsert is by-slug so a partial set
  can't delete existing rows.
- Config to add: `SCHOLAR_PAGE_SIZE=20`, `SCHOLAR_MAX_PAGES`, inter-page delay.
- Accuracy guard: a deterministic per-page ID count (ujin `links` mode) can
  cross-check that extraction captured every row the page listed — a real `qa`
  signal. Add the `pagesize` accuracy sweep to `experiments/run.py` to confirm 20
  is the right chunk before scaling.

## Already in place (single-page path)
`obscura_client` + the Scholar branch in `orchestrate` already render one page
and extract it (verified: 14 pubs for Ashjaee, who fits on one page). Profiles
that fit on one page work today; only multi-page profiles wait on the above.
