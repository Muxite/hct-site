"""Rebuild the frontend's offline snapshot's project tables from projects.yaml.

``frontend/src/data/snapshot.json`` is what the site renders in ``VITE_MOCK``
mode — a committed dump of the live Supabase tables so the frontend can be
developed (and demoed) with no keys and no network. Its ``research`` rows went
stale when the 60-project legacy archive landed in ``projects.yaml``.

This is the offline half of the archive rollout; the online half is
``hct-manager sync-content``, which pushes the same YAML to Supabase. Both read
``load_projects_yaml``, so they share one source of truth — the published data
still diverges until each side is actually re-run.

Deterministic: local YAML in, local JSON out. No network, no LLM, no keys.

    cd backend && PYTHONPATH=. python3 -m src.snapshot
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
