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
