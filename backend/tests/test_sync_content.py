"""Unit tests for the YAML -> Supabase people/research sync (no network)."""

from __future__ import annotations

import pytest

from src.sync_content import (
    ContentError,
    dump_people_yaml,
    dump_research_yaml,
    load_people_yaml,
    load_research_yaml,
    sync_content,
)

PEOPLE_YAML = """\
people:
  - name: Sidney Fels
    role: Professor
    email: ssfels@ece.ubc.ca
    photo: assets/img/sid.png
    status: current
  - name: Past Student
    role: PhD (graduated 2021)
    status: alumni
  - name: Implicit Current
    role: MASc Student
"""

RESEARCH_YAML = """\
research:
  - title: Brain2Speech
    tagline: BCIs and 3D biomechanical articulatory speech synthesis
    link: https://hct.ece.ubc.ca/brain2speech/
    status: current
  - title: ViDeX
    tagline: Teaching and learning experiences with video
    status: current
  - title: Old Project
    status: archived
"""


class FakeSupabase:
    def __init__(self):
        self.replaced: dict[str, tuple[list[dict], str]] = {}

    def replace(self, table, rows, *, key):
        rows = list(rows)
        self.replaced[table] = (rows, key)
        return len(rows)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_people_yaml(tmp_path):
    people = load_people_yaml(_write(tmp_path, "people.yaml", PEOPLE_YAML))
    assert [p.name for p in people] == ["Sidney Fels", "Past Student", "Implicit Current"]
    assert [p.kind for p in people] == ["current", "alumni", "current"]
    assert [p.sort_order for p in people] == [0, 1, 2]  # list order wins
    assert people[0].email == "ssfels@ece.ubc.ca"


def test_load_research_yaml(tmp_path):
    projects = load_research_yaml(_write(tmp_path, "research.yaml", RESEARCH_YAML))
    assert [r.title for r in projects] == ["Brain2Speech", "ViDeX", "Old Project"]
    assert [r.kind for r in projects] == ["current", "current", "archived"]
    assert projects[0].link == "https://hct.ece.ubc.ca/brain2speech/"


def test_kind_alias_accepted(tmp_path):
    p = _write(tmp_path, "people.yaml", "people:\n  - name: X\n    kind: alumni\n")
    assert load_people_yaml(p)[0].kind == "alumni"


def test_bad_status_raises(tmp_path):
    p = _write(tmp_path, "people.yaml", "people:\n  - name: X\n    status: gone\n")
    with pytest.raises(ContentError, match="gone"):
        load_people_yaml(p)
    r = _write(tmp_path, "research.yaml", "research:\n  - title: Y\n    status: alumni\n")
    with pytest.raises(ContentError, match="alumni"):
        load_research_yaml(r)  # people-vocabulary status on a research row


def test_missing_file_raises(tmp_path):
    with pytest.raises(ContentError, match="not found"):
        load_people_yaml(tmp_path / "nope.yaml")


def test_empty_or_misshapen_yaml_raises(tmp_path):
    with pytest.raises(ContentError, match="non-empty"):
        load_people_yaml(_write(tmp_path, "a.yaml", "people: []\n"))
    with pytest.raises(ContentError, match="non-empty"):
        load_research_yaml(_write(tmp_path, "b.yaml", "other: 1\n"))
    with pytest.raises(ContentError, match="not a mapping"):
        load_people_yaml(_write(tmp_path, "c.yaml", "people:\n  - just-a-string\n"))


def test_invalid_row_raises(tmp_path):
    p = _write(tmp_path, "people.yaml", "people:\n  - role: No Name\n")
    with pytest.raises(ContentError, match=r"people\[0\]"):
        load_people_yaml(p)


def test_sync_content_replaces_both_tables(tmp_path):
    sb = FakeSupabase()
    n_people, n_research = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    assert (n_people, n_research) == (3, 3)
    people_rows, people_key = sb.replaced["people"]
    assert people_key == "name"
    assert people_rows[1]["kind"] == "alumni"
    research_rows, research_key = sb.replaced["research"]
    assert research_key == "title"
    assert research_rows[2] == {
        "title": "Old Project", "tagline": None, "description": None,
        "link": None, "image": None, "kind": "archived", "sort_order": 2,
    }


def test_sync_content_validates_before_writing(tmp_path):
    sb = FakeSupabase()
    good = _write(tmp_path, "people.yaml", PEOPLE_YAML)
    bad = _write(tmp_path, "research.yaml", "research:\n  - title: X\n    status: nope\n")
    with pytest.raises(ContentError):
        sync_content(good, bad, supabase=sb)
    assert sb.replaced == {}  # nothing written: no half-sync


def test_people_yaml_round_trip(tmp_path):
    p = _write(tmp_path, "people.yaml", PEOPLE_YAML)
    before = load_people_yaml(p)
    dump_people_yaml(p, before)
    after = load_people_yaml(p)
    assert [(x.name, x.role, x.email, x.photo, x.kind) for x in after] == [
        (x.name, x.role, x.email, x.photo, x.kind) for x in before
    ]


def test_research_yaml_round_trip(tmp_path):
    p = _write(tmp_path, "research.yaml", RESEARCH_YAML)
    before = load_research_yaml(p)
    dump_research_yaml(p, before)
    after = load_research_yaml(p)
    assert [(x.title, x.tagline, x.link, x.image, x.kind) for x in after] == [
        (x.title, x.tagline, x.link, x.image, x.kind) for x in before
    ]


def test_dump_people_yaml_preserves_header_comment(tmp_path):
    src = "# keep this header\n# second line\n" + PEOPLE_YAML
    p = _write(tmp_path, "people.yaml", src)
    dump_people_yaml(p, load_people_yaml(p))
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# keep this header\n# second line\n")