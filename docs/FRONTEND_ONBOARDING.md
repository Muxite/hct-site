# Frontend Onboarding — HCT Lab Publications

Welcome. You're building the **Publications** part of the HCT Lab website. This
doc tells you everything you need to do that and **nothing about how the data is
produced** — you don't need it. There's a backend service in a Docker container.
You start the container, it serves an HTTP API, you call that API, you get clean
JSON, you render it. That's the whole relationship.

> **Status (read this):** The API described here is the **contract** between you
> and the backend. The backend (`hct-manager`) currently runs as a one-shot
> command-line tool that writes a `publications.yaml` file; the FastAPI wrapper
> described below is being added so you have a normal HTTP API to build against.
> Build to this contract. If an endpoint isn't live yet, you can mock it from
> the example responses here — the shapes are real (they come straight from the
> backend's data model).

---

## 1. The mental model

```
   ┌─────────────────────────────┐
   │  Docker container            │        you, the frontend
   │  "hct-manager" (FastAPI)     │   ◄── HTTP (JSON) ──►   browser / your app
   │                              │
   │  [black box: scraping +      │        GET /publications
   │   AI + validation happen     │        GET /publications/{id}
   │   in here — not your problem]│        POST /refresh
   └─────────────────────────────┘
```

- It's a **normal REST API**. Call it with `fetch`, axios, whatever.
- Responses are **JSON** (not YAML — you may see `.yaml` mentioned elsewhere in
  the repo; that's the backend's internal storage, ignore it).
- The container is the only thing you talk to. You never call Google Scholar,
  an LLM, or anything else directly.

---

## 2. Get it running locally

You need **Docker** (Docker Desktop, or `docker` + `docker compose` on Linux).

```bash
# from the repo root
cd backend

# (one time) the backend needs an API key for its AI step — but YOU don't.
# If you don't have .env, ask whoever owns the backend for one, or:
cp ../.env.example ../.env   # the demo may run without a real key for read-only endpoints

# start the API
docker compose up -d hct-manager
```

The API will be reachable at:

```
http://localhost:8902
```

> Port note: `8901` is the internal scraper (`ujin`) — ignore it. Your API is
> **8902**. If that port is wrong when you try it, check `backend/docker-compose.yml`
> or ask the backend owner.

**First thing to do once it's up:** open the interactive API docs in your
browser:

```
http://localhost:8902/docs
```

FastAPI auto-generates a full Swagger UI there. You can see every endpoint, the
exact response shape, and click "Try it out" to fire real requests without
writing any code. This is the fastest way to understand what you're getting.

---

## 3. The API

Base URL: `http://localhost:8902`

### `GET /health`
Liveness check. Use it to confirm the container is up.

```json
{ "status": "ok" }
```

### `GET /publications`
**This is the main one.** Returns the full set of publications.

```json
{
  "generated_at": "2026-06-02T11:42:20Z",
  "publications": [
    {
      "id": "zhu2022-a-unified-representation-of-control-logic-in",
      "title": "A unified representation of control logic in human-ultrasound machine interaction",
      "authors": [
        "Hongzhi Zhu",
        "Yasmin Halwani",
        "Robert Rohling",
        "Sidney Fels",
        "Septimiu Salcudean"
      ],
      "year": 2022,
      "type": "article",
      "venue": "IEEE Journal of Biomedical and Health Informatics",
      "link": null,
      "bibtex": null,
      "description": null
    }
  ]
}
```

### `GET /publications/{id}`
A single publication by its `id`. `404` if it doesn't exist.

### `POST /refresh`  *(optional / admin)*
Tells the backend to go check the source pages and regenerate the list. This is
the "update the data" button. It can take a while (it scrapes + runs AI), so
treat it as a background action — fire it, then poll `GET /publications` again.

```jsonc
// optional body
{ "force": true }   // re-extract everything, even if nothing changed
```

You usually **don't need this** for building the UI — `GET /publications`
already returns whatever data exists. Wire `POST /refresh` to an admin button
only if the demo calls for "refresh now."

---

## 4. The publication object — field reference

Every entry in `publications[]` has exactly this shape. This is authoritative
(it's the backend's validated data model — bad data never reaches you):

| Field         | Type                | Notes                                                        |
|---------------|---------------------|--------------------------------------------------------------|
| `id`          | string              | Stable unique slug. Safe to use as a React `key`.            |
| `title`       | string              | Always present, non-empty.                                   |
| `authors`     | string[]            | Ordered, at least one. Render order = author order.          |
| `year`        | number              | Integer, e.g. `2022`.                                        |
| `type`        | string (enum)       | One of the values below. Default `misc`.                     |
| `venue`       | string \| **null**  | Journal/conference name. **May be null.**                    |
| `link`        | string \| **null**  | DOI/URL, starts with `http`. **May be null.**                |
| `bibtex`      | string \| **null**  | Raw BibTeX. **May be null.**                                 |
| `description` | string \| **null**  | Optional longer blurb. **May be null.**                      |

`type` is one of:
`article`, `inproceedings`, `preprint`, `book`, `incollection`, `thesis`,
`techreport`, `misc`.

**Important:** `venue`, `link`, `bibtex`, and `description` are **nullable**.
Always guard for `null` before rendering (e.g. show a struck-through "link" when
`link` is null). The required fields (`id`, `title`, `authors`, `year`, `type`)
are always there.

---

## 5. A worked example

A complete, dependency-free render. Adapt to your framework.

```js
async function loadPublications() {
  const res = await fetch("http://localhost:8902/publications");
  if (!res.ok) throw new Error(`API returned ${res.status}`);
  const data = await res.json();          // { generated_at, publications: [...] }
  return data.publications ?? [];
}

function groupByYear(pubs) {
  const groups = new Map();
  for (const p of pubs) {
    if (!groups.has(p.year)) groups.set(p.year, []);
    groups.get(p.year).push(p);
  }
  // newest year first
  return [...groups.entries()].sort((a, b) => b[0] - a[0]);
}

function renderEntry(p) {
  const authors = (p.authors ?? []).join("; ");
  const venue = p.venue ? `${p.venue}, ` : "";
  const link = p.link ? `<a href="${p.link}">link</a>` : "<s>link</s>";
  const desc = p.description ? `<p class="pub-desc">${p.description}</p>` : "";
  return `
    <div class="pub-entry">
      <div>${authors}</div>
      <div><strong>${p.title}</strong></div>
      <div class="pub-meta">${venue}${p.year} [${p.type}]</div>
      <div>${link}</div>
      ${desc}
    </div>`;
}

loadPublications().then((pubs) => {
  const html = groupByYear(pubs)
    .map(([year, entries]) =>
      `<h3>${year}</h3>${entries.map(renderEntry).join("")}`
    ).join("");
  document.querySelector("#publications-list").innerHTML = html;
});
```

> ⚠️ The snippet above does **no HTML escaping** — fine for a demo with trusted
> data, but escape user-facing strings before production. There's already a
> tested escaper + renderer you can reuse: see
> `frontend/hct-render/renderers/publications.js` (it currently fetches YAML;
> the only change for the API is feeding it JSON from `fetch().json()` instead
> of parsing YAML text).

---

## 6. What already exists in this repo

You're not starting from zero:

```
frontend/
  index.html                          the site shell (HCT Lab page). The
                                        Publications section is the part you own.
  hct-render/
    renderers/publications.js          a working renderer (grouping by year,
                                        HTML escaping, null-safe link/bibtex/desc)
    renderers/publications.test.js     unit tests for it  (run: npm test)
```

The existing renderer was written against a YAML file fetched by the browser.
For the API demo you have two choices:

1. **Reuse it as-is** — keep pointing it at the YAML file the backend writes
   (`frontend/data/publications.yaml`). Zero API needed. Simplest possible demo.
2. **Switch it to the API** — replace its "fetch YAML text + parse" step with
   "fetch JSON" against `GET /publications`. The render logic is identical; the
   object shape is the same.

Pick based on whether the demo needs to show a *live API* or just a *working
page*. Talk to the backend owner about which they're demoing.

Run the existing frontend tests:

```bash
cd frontend/hct-render && npm test
```

---

## 7. Things that will trip you up (read before you debug for an hour)

- **CORS.** If you serve your frontend from a different origin (e.g. a Vite dev
  server on `:5173`) and call the API on `:8902`, the browser may block it. The
  backend needs to allow your origin (FastAPI CORS middleware). If you get a
  CORS error in the console, that's a **backend config** ask — tell the backend
  owner your dev origin and they'll allow it.
- **Empty list is normal.** A fresh container may return `"publications": []`
  until a refresh has run. Handle the empty state in the UI ("No publications
  yet").
- **Nulls everywhere optional fields live.** See §4. Guard them.
- **`/refresh` is slow.** It's not a normal request — it kicks off scraping +
  AI. Don't block your UI on it; fire-and-poll.
- **Don't read the YAML and the API at the same time** and expect them to differ
  — they're the same data, just two access methods. Pick one for your demo.

---

## 8. What is *not* your problem

Genuinely ignore all of this — it lives inside the container:

- How pages get scraped (a service called `ujin`).
- The AI model that reads pages and extracts papers.
- Data validation, change detection, fingerprints, prompts, API keys for the AI.
- Where the data is stored (`publications.yaml` is an internal detail).

If the data looks wrong (missing paper, wrong year), that's a **backend** issue —
report it, don't try to fix it in the frontend.

---

## 9. This is a demo, not the destination

For context (you don't need to act on it): the long-term plan is for the data to
live in a database (Supabase) that the frontend queries directly. The current
container + API exists so we can **demo a working, end-to-end page now**. The
object shape in §4 is intended to stay stable across that move, so building
against it today is not throwaway work.

See `PLANS.md` and `docs/ARCHITECTURE.md` if you're curious about the bigger
picture — but you don't need either to do your job.

---

## 10. Quickstart checklist

1. `cd backend && docker compose up -d hct-manager`
2. Open `http://localhost:8902/docs` — confirm it loads, click around.
3. `curl http://localhost:8902/publications` — confirm you get JSON.
4. Render `data.publications` grouped by year (see §5), guard nulls (§4).
5. Stuck on CORS / empty data / a missing endpoint? → §7, then ping the backend owner.
