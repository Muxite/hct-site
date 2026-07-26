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
    """Records every call *and* keeps a ``live`` dict simulating what's
    actually in Supabase, so the diff-based bulk sync's insert/delete/
    fill-if-empty behavior can be proven end-to-end (not just "the right
    method was called with the right args" -- the ``live`` state changes
    only where the real PostgREST semantics say it should).
    """

    def __init__(self, live: dict[str, list[dict]] | None = None):
        self.live: dict[str, list[dict]] = {
            t: [dict(r) for r in rows] for t, rows in (live or {}).items()
        }
        self.replaced: dict[str, tuple[list[dict], str]] = {}
        self.upserted: dict[str, tuple[list[dict], str | None]] = {}
        self.inserted_missing: dict[str, tuple[list[dict], str]] = {}
        self.deletes: list[tuple[str, dict]] = []
        self.updates: list[tuple[str, dict, dict]] = []

    def select(self, table, *, columns="*", params=None):
        rows = self.live.get(table, [])
        if columns == "*":
            return [dict(r) for r in rows]
        cols = [c.strip() for c in columns.split(",")]
        return [{c: r.get(c) for c in cols} for r in rows]

    def replace(self, table, rows, *, key):
        rows = list(rows)
        self.replaced[table] = (rows, key)
        self.live[table] = [dict(r) for r in rows]
        return len(rows)

    def upsert(self, table, rows, *, on_conflict=None):
        rows = list(rows)
        self.upserted[table] = (rows, on_conflict)
        live = self.live.setdefault(table, [])
        for row in rows:
            existing = None
            if on_conflict:
                existing = next(
                    (r for r in live if r.get(on_conflict) == row.get(on_conflict)), None
                )
            if existing is not None:
                existing.update(row)  # merge-duplicates: only sent columns change
            else:
                live.append(dict(row))
        return len(rows)

    def insert_missing(self, table, rows, *, key):
        rows = list(rows)
        self.inserted_missing[table] = (rows, key)
        existing_keys = {r.get(key) for r in self.live.get(table, [])}
        new_rows = [r for r in rows if r.get(key) not in existing_keys]
        self.live.setdefault(table, []).extend(dict(r) for r in new_rows)
        return len(new_rows)

    def delete(self, table, *, params):
        self.deletes.append((table, dict(params)))
        for col, filt in params.items():
            if filt.startswith("eq."):
                val = filt[len("eq.") :]
                self.live[table] = [
                    r for r in self.live.get(table, []) if str(r.get(col)) != val
                ]

    def update(self, table, values, *, params):
        self.updates.append((table, dict(values), dict(params)))
        eq_col = eq_val = null_col = None
        for col, filt in params.items():
            if filt == "is.null":
                null_col = col
            elif filt.startswith("eq."):
                eq_col, eq_val = col, filt[len("eq.") :]
        for row in self.live.get(table, []):
            if eq_col is not None and str(row.get(eq_col)) != eq_val:
                continue
            if null_col is not None and row.get(null_col) is not None:
                continue  # real PostgREST server-side is.null filter
            row.update(values)


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
    # fill-if-empty PATCH; Old Project sets none, so no PATCH for it. (people
    # gets its own fill-if-empty PATCHes for role/email/photo now too -- see
    # test_sync_content_people_bulk_sync_inserts_deletes_and_fills_only_empty
    # -- so filter by table here.)
    research_updates = [u for u in sb.updates if u[0] == "research"]
    assert research_updates == [
        ("research", {"tagline": "BCIs and 3D biomechanical articulatory speech synthesis"},
         {"slug": "eq.brain2speech", "tagline": "is.null"}),
        ("research", {"tagline": "Teaching and learning experiences with video"},
         {"slug": "eq.videx", "tagline": "is.null"}),
    ]


def test_sync_content_people_upserts_via_bulk_sync_not_replace(tmp_path):
    sb = FakeSupabase()
    n_people, n_research = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    assert (n_people, n_research) == (3, 3)
    people_rows, on_conflict = sb.upserted["people"]
    assert on_conflict == "name"
    assert people_rows[1]["kind"] == "alumni"
    assert "people" not in sb.replaced
    assert "people" not in sb.inserted_missing


def test_sync_content_people_bulk_sync_inserts_deletes_and_fills_only_empty(tmp_path):
    """The three-way bulk-sync contract for `people`, proven against live state:
    a new YAML name is inserted, a name dropped from the YAML is deleted (delete
    propagation), and for a name present in both, structural fields (kind,
    sort_order) always follow the YAML while the presentational subset
    (role/email/photo/bio) is only filled in where still empty -- an
    already-set value survives untouched.
    """
    sb = FakeSupabase(
        live={
            "people": [
                {
                    "name": "Sidney Fels", "role": "Old role should survive",
                    "email": "old@example.com", "photo": None, "bio": None,
                    "kind": "alumni", "sort_order": 9,
                },
                {
                    "name": "Departed Person", "role": "Ex", "email": None,
                    "photo": None, "bio": None, "kind": "alumni", "sort_order": 1,
                },
            ]
        }
    )
    n_people, _ = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    assert n_people == 3
    live_names = {p["name"] for p in sb.live["people"]}
    # No longer in people.yaml -> deleted (restores replace()'s old propagation).
    assert "Departed Person" not in live_names
    assert sb.deletes == [("people", {"name": "eq.Departed Person"})]
    # New names inserted.
    assert {"Past Student", "Implicit Current"} <= live_names
    sidney = next(p for p in sb.live["people"] if p["name"] == "Sidney Fels")
    # Structural fields always follow the YAML (this is *why* people.yaml
    # exists -- e.g. flipping someone to alumni when they graduate).
    assert sidney["kind"] == "current"
    assert sidney["sort_order"] == 0
    # Presentational fields already set survive a routine resync untouched.
    assert sidney["role"] == "Old role should survive"
    assert sidney["email"] == "old@example.com"


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


def test_sync_content_research_bulk_sync_inserts_deletes_and_fills_only_empty(tmp_path):
    """Same three-way contract as people, for `research` (legacy research.yaml
    path): insert new, delete a slug no longer present, and for a matched
    slug, structural fields (title/kind/sort_order/link) always follow the
    YAML while tagline/summary/hero_image are fill-if-empty only.
    """
    sb = FakeSupabase(
        live={
            "research": [
                {
                    "title": "Brain2Speech (stale title)", "slug": "brain2speech",
                    "tagline": "Existing tagline should survive", "description": None,
                    "summary": None, "link": None, "image": None, "hero_image": None,
                    "kind": "archived", "sort_order": 9,
                },
                {
                    "title": "Retired Project", "slug": "retired-project", "tagline": None,
                    "description": None, "summary": None, "link": None, "image": None,
                    "hero_image": None, "kind": "archived", "sort_order": 1,
                },
            ]
        }
    )
    _, n_research = sync_content(
        _write(tmp_path, "people.yaml", PEOPLE_YAML),
        _write(tmp_path, "research.yaml", RESEARCH_YAML),
        supabase=sb,
    )
    assert n_research == 3
    live_slugs = {r["slug"] for r in sb.live["research"]}
    # No longer in research.yaml -> deleted.
    assert "retired-project" not in live_slugs
    assert sb.deletes == [("research", {"slug": "eq.retired-project"})]
    assert {"videx", "old-project"} <= live_slugs
    b2s = next(r for r in sb.live["research"] if r["slug"] == "brain2speech")
    # Structural fields always follow research.yaml.
    assert b2s["title"] == "Brain2Speech"
    assert b2s["kind"] == "current"
    assert b2s["sort_order"] == 0
    assert b2s["link"] == "https://hct.ece.ubc.ca/brain2speech/"
    # tagline already set -> untouched by the fill-if-empty PATCH.
    assert b2s["tagline"] == "Existing tagline should survive"


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
    assert sb.deletes == []
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