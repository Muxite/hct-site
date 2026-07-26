"""People + research projects from editable YAML files -> Supabase.

The lab roster and project list change over time (members graduate, projects
wrap up) and the site must distinguish *current* from *archived*. That status
isn't derivable from anything scrapeable, so it lives in two human-edited YAML
files dropped into the mounted inbox folder:

``people.yaml``::

    people:
      - name: Sidney Fels
        role: Professor
        email: ssfels@ece.ubc.ca
        photo: assets/img/fels.jpg
        status: current        # current | alumni

``research.yaml``::

    research:
      - title: Brain2Speech
        tagline: State-of-the-art BCIs and 3D articulatory speech synthesis
        link: https://...
        image: assets/img/b2s.png
        status: current        # current | archived

Edit a file and re-run ``hct-manager sync-content``: list order becomes
``sort_order`` and validation is the normal Pydantic contract
(:class:`~src.models.Person` / :class:`~src.models.ResearchProject`) — a
typo'd status fails loudly instead of landing in the database. The sync is
**non-destructive**, not a wholesale replace: ``people`` is additive-only (a
name already in the table is left completely untouched, even if the YAML now
disagrees with it — see :meth:`~src.supabase_client.SupabaseClient.insert_missing`),
and ``research``'s ``tagline``/``summary``/``hero_image`` are only filled in
when still empty, never overwritten. This is so an admin editing those tables
directly (see the CMS work building on this) can never have their edits
clobbered by a routine re-sync.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.content import dump_yaml_with_header
from src.models import Person, ProjectPerson, ResearchProject

_PEOPLE_KINDS = {"current", "alumni"}
_RESEARCH_KINDS = {"current", "archived"}


class ContentError(ValueError):
    """Raised when a content YAML file is missing, malformed, or invalid."""


def _load_items(path: str | Path, top_key: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise ContentError(f"{p} not found")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    items = data.get(top_key)
    if not isinstance(items, list) or not items:
        raise ContentError(f"{p}: expected a non-empty '{top_key}:' list")
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContentError(f"{p}: entry {i} under '{top_key}:' is not a mapping")
        out.append(dict(item))
    return out


def _take_kind(item: dict[str, Any], allowed: set[str], where: str) -> str:
    # Accept either spelling; 'status' reads better in a hand-edited file.
    kind = str(item.pop("status", None) or item.pop("kind", None) or "current")
    kind = kind.strip().lower()
    if kind not in allowed:
        raise ContentError(
            f"{where}: status '{kind}' is not one of {sorted(allowed)}"
        )
    return kind


def load_people_yaml(path: str | Path) -> list[Person]:
    """Parse ``people.yaml`` into validated rows; list order -> sort_order."""

    people = []
    for i, item in enumerate(_load_items(path, "people")):
        kind = _take_kind(item, _PEOPLE_KINDS, f"{path}: people[{i}]")
        item.pop("sort_order", None)  # order comes from the list itself
        try:
            people.append(Person(**item, kind=kind, sort_order=i))
        except Exception as e:
            raise ContentError(f"{path}: people[{i}] invalid: {e}") from e
    return people


def load_research_yaml(path: str | Path) -> list[ResearchProject]:
    """Parse ``research.yaml`` into validated rows; list order -> sort_order."""

    projects = []
    for i, item in enumerate(_load_items(path, "research")):
        kind = _take_kind(item, _RESEARCH_KINDS, f"{path}: research[{i}]")
        item.pop("sort_order", None)
        try:
            projects.append(ResearchProject(**item, kind=kind, sort_order=i))
        except Exception as e:
            raise ContentError(f"{path}: research[{i}] invalid: {e}") from e
    return projects


def _project_people(item: dict[str, Any], project_slug: str, where: str) -> list[ProjectPerson]:
    """Parse a project entry's ``people:`` list into ``ProjectPerson`` links.

    Each entry is either a bare name (``- Sidney Fels``) or a mapping
    (``{name: Sidney Fels, role: lead}``). List order becomes ``sort_order``.
    """

    raw = item.pop("people", None) or []
    if not isinstance(raw, list):
        raise ContentError(f"{where}: 'people' must be a list")
    links = []
    for j, person in enumerate(raw):
        if isinstance(person, str):
            name, role = person, None
        elif isinstance(person, dict) and person.get("name"):
            name = str(person["name"])
            role = person.get("role") or person.get("role_on_project")
        else:
            raise ContentError(f"{where}: people[{j}] must be a name or a {{name, role}} mapping")
        links.append(
            ProjectPerson(
                project_slug=project_slug,
                person_name=name,
                role_on_project=str(role) if role else None,
                sort_order=j,
            )
        )
    return links


def _project_papers(item: dict[str, Any], where: str) -> list[str]:
    """Parse a project entry's ``papers:`` list into a list of publication slugs."""

    raw = item.pop("papers", None) or []
    if not isinstance(raw, list):
        raise ContentError(f"{where}: 'papers' must be a list of publication slugs")
    slugs = []
    for j, paper in enumerate(raw):
        slug = paper.get("slug") if isinstance(paper, dict) else paper
        if not isinstance(slug, str) or not slug.strip():
            raise ContentError(f"{where}: papers[{j}] must be a publication slug")
        slugs.append(slug.strip())
    return slugs


def load_projects_yaml(
    path: str | Path,
) -> tuple[list[ResearchProject], list[ProjectPerson], list[tuple[str, str]]]:
    """Parse ``projects.yaml`` into project rows, people links, and paper membership.

    ``projects.yaml`` is the project-centric source of truth (see docs/PROJECTS.md):
    each entry is a research project plus the lab ``people`` involved and the
    publication ``papers`` slugs that belong to it. Returns ``(projects, links,
    membership)`` where ``membership`` is a list of ``(project_slug, paper_slug)``
    pairs used to stamp ``publications.project_slug``.
    """

    projects: list[ResearchProject] = []
    links: list[ProjectPerson] = []
    membership: list[tuple[str, str]] = []
    for i, item in enumerate(_load_items(path, "projects")):
        where = f"{path}: projects[{i}]"
        kind = _take_kind(item, _RESEARCH_KINDS, where)
        item.pop("sort_order", None)
        # Pull the relational fields out before validating the project row.
        people_raw = item  # people/papers popped in place by the helpers below
        try:
            slug = str(item.get("slug") or "").strip() or None
            if not slug:
                from src.models import project_slug_for

                slug = project_slug_for(str(item.get("title", "")))
            links.extend(_project_people(people_raw, slug, where))
            paper_slugs = _project_papers(people_raw, where)
            project = ResearchProject(**item, kind=kind, sort_order=i).with_slug()
        except ContentError:
            raise
        except Exception as e:
            raise ContentError(f"{where} invalid: {e}") from e
        projects.append(project)
        membership.extend((project.slug, ps) for ps in paper_slugs)
    return projects, links, membership


# Presentational research/project fields that a later admin edit may set
# directly in Supabase; a YAML re-sync must never overwrite them once they're
# non-empty, so they're excluded from the main upsert and only "filled" while
# still null (see _sync_research / _fill_if_empty).
_RESEARCH_FILL_FIELDS = ("tagline", "summary", "hero_image")


def _fill_if_empty(
    supabase: Any, table: str, key: str, row: dict[str, Any], fields: tuple[str, ...]
) -> None:
    """PATCH each of ``fields`` on the row keyed by ``row[key]``, one field at a
    time, but only where that column is currently null.

    The ``is.null`` half of the filter runs server-side (not a read-then-write
    check), so there's no race with a concurrent write and no way for this to
    clobber a value an admin (or an earlier sync/describe run) already set.
    A field the YAML doesn't set (falsy) is skipped entirely — an empty value
    never overwrites anything, present or absent.
    """

    key_val = row[key]
    for field in fields:
        value = row.get(field)
        if not value:
            continue
        supabase.update(
            table,
            {field: value},
            params={key: f"eq.{key_val}", field: "is.null"},
        )


def _sync_research(supabase: Any, rows: list[dict[str, Any]]) -> int:
    """Upsert ``research`` rows without ever overwriting an already-set
    ``tagline``/``summary``/``hero_image``.

    The main payload (keyed on ``slug``, which every row has via
    :meth:`~src.models.ResearchProject.row`) omits those three columns
    entirely, so a re-sync can freely update title/link/image/kind/sort_order
    while leaving the presentational fields alone; a follow-up fill-if-empty
    PATCH sets them only where still null. Returns the row count sent.
    """

    payload = [
        {k: v for k, v in row.items() if k not in _RESEARCH_FILL_FIELDS}
        for row in rows
    ]
    n = supabase.upsert("research", payload, on_conflict="slug")
    for row in rows:
        _fill_if_empty(supabase, "research", "slug", row, _RESEARCH_FILL_FIELDS)
    return n


def _stamp_project_slugs(supabase: Any, membership: list[tuple[str, str]]) -> int:
    """Set ``publications.project_slug`` from ``membership`` (only existing rows).

    Clears every existing stamp first (so a paper dropped from all projects
    reverts to timeline-only), then PATCHes each project's papers by slug. Papers
    not present in ``publications`` are simply not matched. Returns the number of
    (project, paper) links applied.
    """

    # Clear all current stamps in one PATCH, then re-apply per project.
    supabase.update("publications", {"project_slug": None}, params={"project_slug": "not.is.null"})
    by_project: dict[str, list[str]] = {}
    for proj_slug, paper_slug in membership:
        by_project.setdefault(proj_slug, []).append(paper_slug)
    for proj_slug, slugs in by_project.items():
        # Slugs are ascii kebab-case, so no quoting is needed inside in.(...).
        supabase.update(
            "publications",
            {"project_slug": proj_slug},
            params={"slug": f"in.({','.join(slugs)})"},
        )
    return len(membership)


def _person_to_yaml(p: Person) -> dict[str, Any]:
    """Hand-authored fields only (name/role/email/photo/status), empties dropped."""
    d: dict[str, Any] = {"name": p.name}
    if p.role:
        d["role"] = p.role
    if p.email:
        d["email"] = p.email
    if p.photo:
        d["photo"] = p.photo
    d["status"] = p.kind
    return d


def _research_to_yaml(r: ResearchProject) -> dict[str, Any]:
    """Hand-authored fields only (title/tagline/link/image/status), empties dropped."""
    d: dict[str, Any] = {"title": r.title}
    if r.tagline:
        d["tagline"] = r.tagline
    if r.link:
        d["link"] = r.link
    if r.image:
        d["image"] = r.image
    d["status"] = r.kind
    return d


def dump_people_yaml(path: str | Path, people: list[Person]) -> None:
    """Write ``people`` back to ``people.yaml`` (inverse of :func:`load_people_yaml`).

    List order is the display order; ``sort_order`` is implicit and dropped, and
    the AI-written ``bio`` is not round-tripped (it isn't a hand-authored field).
    """
    dump_yaml_with_header(path, {"people": [_person_to_yaml(p) for p in people]})


def dump_research_yaml(path: str | Path, projects: list[ResearchProject]) -> None:
    """Write ``research`` back to ``research.yaml`` (inverse of the loader).

    Only hand-authored fields are written; the AI-written ``description`` is not
    round-tripped.
    """
    dump_yaml_with_header(path, {"research": [_research_to_yaml(r) for r in projects]})


def sync_content(
    people_path: str | Path,
    research_path: str | Path,
    *,
    supabase: Any,
    projects_path: str | Path | None = None,
) -> tuple[int, int]:
    """Sync the ``people`` and ``research`` tables from the YAML files.

    When ``projects_path`` is given and exists, it is the project source of
    truth (see docs/PROJECTS.md): the ``research`` table, the ``project_people``
    links, and each paper's ``publications.project_slug`` are all synced from it,
    and ``research_path`` is ignored. Otherwise the legacy ``research.yaml`` path
    is used and no project relationships are written.

    Non-destructive: ``people`` is additive-only (:meth:`SupabaseClient.insert_missing`
    — a name already present is left untouched), and ``research``'s
    ``tagline``/``summary``/``hero_image`` are only filled in where still empty
    (see :func:`_sync_research`). Everything else about a matched ``research``
    row (title, link, image, kind, sort_order) does still update on every sync.

    Returns ``(people_written, research_written)``. Every file is parsed and
    validated *before* the first write, so a broken file never half-syncs.
    """

    people = load_people_yaml(people_path)
    use_projects = projects_path is not None and Path(projects_path).exists()
    if use_projects:
        projects, links, membership = load_projects_yaml(projects_path)
    else:
        research = load_research_yaml(research_path)

    n_people = supabase.insert_missing("people", [p.row() for p in people], key="name")
    if use_projects:
        n_research = _sync_research(supabase, [p.row() for p in projects])
        supabase.replace("project_people", [l.row() for l in links], key="project_slug")
        _stamp_project_slugs(supabase, membership)
    else:
        n_research = _sync_research(supabase, [r.row() for r in research])
    return n_people, n_research
