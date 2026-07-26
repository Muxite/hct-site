"""Unit tests for the YAML -> Supabase people/research sync (no network)."""

from __future__ import annotations

import pytest

from src.sync_content import (
    ContentError,
    dump_people_yaml,
    dump_research_yaml,
    load_people_yaml,
    load_projects_yaml,
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
        self.upserted: dict[str, tuple[list[dict], str | None]] = {}
        self.inserted_missing: dict[str, tuple[list[dict], str]] = {}
        self.updates: list[tuple[str, dict, dict]] = []

    def replace(self, table, rows, *, key):
        rows = list(rows)
        self.replaced[table] = (rows, key)
        return len(rows)

    def upsert(self, table, rows, *, on_conflict=None):
        rows = list(rows)
        self.upserted[table] = (rows, on_conflict)
        return len(rows)

    def insert_missing(self, table, rows, *, key):
        rows = list(rows)
        self.inserted_missing[table] = (rows, key)
        return len(rows)

    def update(self, table, values, *, params):
        self.updates.append((table, values, params))


PROJECTS_YAML = """\
projects:
  - title: Brain2Speech
    summary: Decoding speech from neural signals.
    hero_image: assets/img/b2s.png
    status: current
    people:
      - name: Sidney Fels
        role: lead
      - Grad Student
    papers:
      - fels2022-brain-to-speech
      - fels2021-articulatory-synth
  - title: ViDeX
    slug: videx
    status: archived
    people: []
    papers:
      - fels2019-videx
"""


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


def test_load_projects_yaml(tmp_path):
    projects, links, membership = load_projects_yaml(
        _write(tmp_path, "projects.yaml", PROJECTS_YAML)
    )
    # Project rows: slug derived when omitted, kept when explicit; extra fields.
    assert [(p.slug, p.kind, p.sort_order) for p in projects] == [
        ("brain2speech", "current", 0),
        ("videx", "archived", 1),
    ]
    assert projects[0].summary == "Decoding speech from neural signals."
    assert projects[0].hero_image == "assets/img/b2s.png"
    # People links: bare name and {name, role} mapping, list order = sort_order.
    assert [(l.project_slug, l.person_name, l.role_on_project, l.sort_order) for l in links] == [
        ("brain2speech", "Sidney Fels", "lead", 0),
        ("brain2speech", "Grad Student", None, 1),
    ]
    # Membership: (project_slug, paper_slug) pairs, ready for stamping.
    assert membership == [
        ("brain2speech", "fels2022-brain-to-speech"),
        ("brain2speech", "fels2021-articulatory-synth"),
        ("videx", "fels2019-videx"),
    ]


def test_projects_bad_people_entry_raises(tmp_path):
    bad = "projects:\n  - title: X\n    people:\n      - {role: lead}\n"
    with pytest.raises(ContentError, match=r"projects\[0\]"):
        load_projects_yaml(_write(tmp_path, "projects.yaml", bad))


def test_sync_content_projects_supersedes_research(tmp_path):
    sb = FakeSupabase()
    n_people, n_research = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
        projects_path=_write(tmp_path, "projects.yaml", PROJECTS_YAML),
    )
    assert (n_people, n_research) == (3, 2)  # research came from projects.yaml
    research_rows, on_conflict = sb.upserted["research"]
    assert on_conflict == "slug"
    assert [r["slug"] for r in research_rows] == ["brain2speech", "videx"]
    assert "research" not in sb.replaced
    # project_people replaced with the two brain2speech links.
    pp_rows, pp_key = sb.replaced["project_people"]
    assert pp_key == "project_slug"
    assert len(pp_rows) == 2
    # Stamping: one clear-all PATCH then one PATCH per project with papers.
    # (research's own fill-if-empty PATCHes land in sb.updates too -- see
    # test_sync_content_projects_fills_only_empty_fields -- so filter by table.)
    pub_updates = [u for u in sb.updates if u[0] == "publications"]
    assert pub_updates[0] == ("publications", {"project_slug": None}, {"project_slug": "not.is.null"})
    stamped = {vals["project_slug"]: params["slug"] for _, vals, params in pub_updates[1:]}
    assert stamped["brain2speech"] == "in.(fels2022-brain-to-speech,fels2021-articulatory-synth)"
    assert stamped["videx"] == "in.(fels2019-videx)"


def test_sync_content_without_projects_uses_research(tmp_path):
    sb = FakeSupabase()
    sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
        projects_path=tmp_path / "absent.yaml",  # does not exist -> legacy path
    )
    research_rows, on_conflict = sb.upserted["research"]
    assert on_conflict == "slug"
    assert [r["title"] for r in research_rows] == ["Brain2Speech", "ViDeX", "Old Project"]
    assert "research" not in sb.replaced
    assert "project_people" not in sb.replaced
    # RESEARCH_YAML sets a tagline for the two current projects -> each gets a
    # fill-if-empty PATCH; Old Project sets none, so no PATCH for it.
    assert sb.updates == [
        ("research", {"tagline": "BCIs and 3D biomechanical articulatory speech synthesis"},
         {"slug": "eq.brain2speech", "tagline": "is.null"}),
        ("research", {"tagline": "Teaching and learning experiences with video"},
         {"slug": "eq.videx", "tagline": "is.null"}),
    ]


def test_sync_content_people_is_insert_missing_not_replace(tmp_path):
    sb = FakeSupabase()
    n_people, n_research = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    assert (n_people, n_research) == (3, 3)
    people_rows, people_key = sb.inserted_missing["people"]
    assert people_key == "name"
    assert people_rows[1]["kind"] == "alumni"
    assert "people" not in sb.replaced


def test_sync_content_research_upsert_excludes_fill_fields(tmp_path):
    sb = FakeSupabase()
    sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    research_rows, research_key = sb.upserted["research"]
    assert research_key == "slug"
    # tagline/summary/hero_image are never part of the main payload -- an
    # upsert can't overwrite what it never sends.
    for row in research_rows:
        assert "tagline" not in row
        assert "summary" not in row
        assert "hero_image" not in row
    assert research_rows[2] == {
        "title": "Old Project", "slug": "old-project",
        "description": None, "link": None, "image": None,
        "kind": "archived", "sort_order": 2,
    }


def test_sync_content_projects_fills_only_empty_fields(tmp_path):
    sb = FakeSupabase()
    sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
        projects_path=_write(tmp_path, "projects.yaml", PROJECTS_YAML),
    )
    research_rows, _ = sb.upserted["research"]
    for row in research_rows:
        assert "summary" not in row and "hero_image" not in row and "tagline" not in row
    # Brain2Speech sets summary + hero_image (no tagline) in PROJECTS_YAML;
    # ViDeX sets none of the three -- only brain2speech gets fill PATCHes.
    research_updates = [u for u in sb.updates if u[0] == "research"]
    assert research_updates == [
        ("research", {"summary": "Decoding speech from neural signals."},
         {"slug": "eq.brain2speech", "summary": "is.null"}),
        ("research", {"hero_image": "assets/img/b2s.png"},
         {"slug": "eq.brain2speech", "hero_image": "is.null"}),
    ]


def test_sync_content_validates_before_writing(tmp_path):
    sb = FakeSupabase()
    good = _write(tmp_path, "people.yaml", PEOPLE_YAML)
    bad = _write(tmp_path, "research.yaml", "research:\n  - title: X\n    status: nope\n")
    with pytest.raises(ContentError):
        sync_content(good, bad, supabase=sb)
    # nothing written: no half-sync
    assert sb.replaced == {}
    assert sb.upserted == {}
    assert sb.inserted_missing == {}
    assert sb.updates == []


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