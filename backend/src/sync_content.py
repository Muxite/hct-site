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

Edit a file, re-run ``hct-manager sync-content``, and the tables are replaced
wholesale (same replace semantics the old HTML migration used) — the YAML is
the source of truth, list order becomes ``sort_order``. Validation is the
normal Pydantic contract (:class:`~src.models.Person` /
:class:`~src.models.ResearchProject`); a typo'd status fails loudly instead of
landing in the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.content import dump_yaml_with_header
from src.models import Person, ResearchProject

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
) -> tuple[int, int]:
    """Replace the ``people`` and ``research`` tables from the YAML files.

    Returns ``(people_written, research_written)``. Both files are parsed and
    validated *before* the first write, so a broken file never half-syncs.
    """

    people = load_people_yaml(people_path)
    research = load_research_yaml(research_path)
    n_people = supabase.replace("people", [p.row() for p in people], key="name")
    n_research = supabase.replace("research", [r.row() for r in research], key="title")
    return n_people, n_research
