"""Unit tests for the localhost admin viewer (FastAPI, no network).

A fake Supabase client records upsert/replace calls and serves canned rows; the
YAML files live under ``tmp_path``. Consistent with the suite's rule that the
network is always mocked.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")  # viewer is an optional extra
pytest.importorskip("multipart")  # python-multipart, for form posts

from fastapi.testclient import TestClient  # noqa: E402

from src.sync_content import load_people_yaml, load_research_yaml  # noqa: E402
from src.content import load_site_yaml  # noqa: E402
from src.viewer import create_app  # noqa: E402

PEOPLE_YAML = """\
# people header — keep me
people:
  - name: Alice
    role: PhD Student
    email: alice@x.edu
    photo: alice.png
    status: current
  - name: Bob
    role: MASc Student
    status: alumni
"""

RESEARCH_YAML = """\
# research header
research:
  - title: Brain2Speech
    tagline: BCIs and speech synthesis
    link: https://x/b2s/
    status: current
"""

SITE_YAML = """\
# site header
site:
  title: HCT Lab
  nav: [Latest, People]
sections:
  vision:
    title: Vision
    text: Our vision.
"""

PUBLICATION = {
    "slug": "fels2022-a-paper",
    "title": "A Paper",
    "authors": ["S Fels", "A Other"],
    "year": 2022,
    "type": "article",
    "venue": "CHI",
    "link": "https://doi.org/10.1/x",
    "bibtex": None,
    "description": None,
    "updated_at": "2022-01-01T00:00:00Z",
}

TIMELINE = {
    "slug": "fels2022-a-paper",
    "title": "A Paper",
    "authors": ["S Fels"],
    "year": 2022,
    "date_label": "2022",
    "blurb": None,
    "position": 0,
}


class FakeSupabase:
    def __init__(self) -> None:
        self.data: dict[str, list[dict]] = {}
        self.calls: list[tuple] = []

    def select(self, table, *, columns="*", params=None):
        return [dict(r) for r in self.data.get(table, [])]

    def upsert(self, table, rows, *, on_conflict=None):
        rows = list(rows)
        self.calls.append(("upsert", table, rows, on_conflict))
        return len(rows)

    def replace(self, table, rows, *, key):
        rows = list(rows)
        self.calls.append(("replace", table, rows, key))
        self.data[table] = rows
        return len(rows)

    def delete_all(self, table, *, key):
        self.data[table] = []

    def calls_for(self, op, table):
        return [c for c in self.calls if c[0] == op and c[1] == table]


@pytest.fixture
def env(tmp_path):
    people = tmp_path / "people.yaml"
    research = tmp_path / "research.yaml"
    site = tmp_path / "site.yaml"
    people.write_text(PEOPLE_YAML, encoding="utf-8")
    research.write_text(RESEARCH_YAML, encoding="utf-8")
    site.write_text(SITE_YAML, encoding="utf-8")

    sb = FakeSupabase()
    sb.data["people"] = [p.row() for p in load_people_yaml(people)]
    sb.data["research"] = [r.row() for r in load_research_yaml(research)]
    sb.data["site_content"] = [c.row() for c in load_site_yaml(site)]
    sb.data["publications"] = [dict(PUBLICATION)]
    sb.data["timeline"] = [dict(TIMELINE)]

    app = create_app(
        supabase=sb, people_path=people, research_path=research, site_path=site
    )
    client = TestClient(app, follow_redirects=False)
    return app, client, sb, {"people": people, "research": research, "site": site}


# -- read -----------------------------------------------------------------
def test_overview_lists_tables_and_counts(env):
    _, client, _sb, _ = env
    body = client.get("/").text
    for name in ("publications", "timeline", "people", "research", "site_content"):
        assert name in body
    assert "2" in body  # 2 people


def test_table_view_renders_rows_and_columns(env):
    _, client, _sb, _ = env
    body = client.get("/t/people").text
    assert "Alice" in body and "Bob" in body
    assert "sort_order" in body and "kind" in body  # schema columns


def test_unknown_table_404(env):
    _, client, _sb, _ = env
    assert client.get("/t/nope").status_code == 404


# -- supabase-backed edits ------------------------------------------------
def test_edit_publication_description_upserts(env):
    _, client, sb, _ = env
    resp = client.post(
        "/t/publications/edit?id=fels2022-a-paper",
        data={"description": "A lab-voice writeup.", "venue": "CHI",
              "link": "https://doi.org/10.1/x", "bibtex": ""},
    )
    assert resp.status_code == 303
    ups = sb.calls_for("upsert", "publications")
    assert ups, "expected an upsert into publications"
    _, _, rows, on_conflict = ups[-1]
    assert on_conflict == "slug"
    assert rows[0]["description"] == "A lab-voice writeup."
    assert rows[0]["bibtex"] is None  # empty -> None


def test_edit_publication_bad_link_rejected(env):
    _, client, sb, _ = env
    resp = client.post(
        "/t/publications/edit?id=fels2022-a-paper",
        data={"description": "", "venue": "", "link": "not-a-url", "bibtex": ""},
    )
    assert resp.status_code == 400
    assert "http" in resp.text
    assert not sb.calls_for("upsert", "publications")  # nothing written


def test_edit_timeline_blurb_upserts(env):
    _, client, sb, _ = env
    resp = client.post(
        "/t/timeline/edit?id=0", data={"blurb": "Newest work.", "date_label": "2022"}
    )
    assert resp.status_code == 303
    _, _, rows, on_conflict = sb.calls_for("upsert", "timeline")[-1]
    assert on_conflict == "position"
    assert rows[0]["blurb"] == "Newest work."


# -- yaml-backed edits ----------------------------------------------------
def test_edit_person_writes_yaml_and_resyncs(env):
    _, client, sb, paths = env
    resp = client.post(
        "/t/people/edit?id=Alice",
        data={"name": "Alice", "role": "Postdoc", "email": "alice@x.edu",
              "photo": "alice.png", "kind": "current"},
    )
    assert resp.status_code == 303
    # YAML rewritten with the new role, header preserved.
    text = paths["people"].read_text(encoding="utf-8")
    assert "Postdoc" in text
    assert "# people header — keep me" in text
    # and the people table was replaced (re-synced).
    assert sb.calls_for("replace", "people")
    people = {p.name: p for p in load_people_yaml(paths["people"])}
    assert people["Alice"].role == "Postdoc"


def test_edit_person_blank_name_rejected_no_write(env):
    _, client, sb, paths = env
    before = paths["people"].read_text(encoding="utf-8")
    resp = client.post(
        "/t/people/edit?id=Alice",
        data={"name": "  ", "role": "X", "email": "", "photo": "", "kind": "current"},
    )
    assert resp.status_code == 400
    assert paths["people"].read_text(encoding="utf-8") == before  # untouched
    assert not sb.calls_for("replace", "people")


def test_edit_person_bad_status_rejected(env):
    _, client, sb, paths = env
    before = paths["people"].read_text(encoding="utf-8")
    resp = client.post(
        "/t/people/edit?id=Alice",
        data={"name": "Alice", "role": "X", "email": "", "photo": "", "kind": "wizard"},
    )
    assert resp.status_code == 400
    assert paths["people"].read_text(encoding="utf-8") == before
    assert not sb.calls_for("replace", "people")


def test_add_person(env):
    _, client, sb, paths = env
    resp = client.post(
        "/t/people/add",
        data={"name": "Carol", "role": "MASc", "email": "", "photo": "", "kind": "current"},
    )
    assert resp.status_code == 303
    names = [p.name for p in load_people_yaml(paths["people"])]
    assert names == ["Alice", "Bob", "Carol"]
    assert sb.calls_for("replace", "people")


def test_add_duplicate_person_rejected(env):
    _, client, _sb, paths = env
    resp = client.post(
        "/t/people/add",
        data={"name": "Alice", "role": "X", "email": "", "photo": "", "kind": "current"},
    )
    assert resp.status_code == 400
    assert len(load_people_yaml(paths["people"])) == 2  # unchanged


def test_delete_person(env):
    _, client, sb, paths = env
    resp = client.post("/t/people/delete?id=Bob")
    assert resp.status_code == 303
    names = [p.name for p in load_people_yaml(paths["people"])]
    assert names == ["Alice"]
    assert sb.calls_for("replace", "people")


def test_publications_not_addable(env):
    _, client, _sb, _ = env
    assert client.get("/t/publications/add").status_code == 404


# -- site_content edit ----------------------------------------------------
def test_edit_site_content_value_json(env):
    _, client, sb, paths = env
    resp = client.post(
        "/t/site_content/edit?id=vision",
        data={"value": '{"title": "Vision", "text": "A new vision."}'},
    )
    assert resp.status_code == 303
    rows = {c.key: c.value for c in load_site_yaml(paths["site"])}
    assert rows["vision"]["text"] == "A new vision."
    assert sb.calls_for("upsert", "site_content")


def test_edit_site_content_bad_json_rejected(env):
    _, client, _sb, paths = env
    resp = client.post(
        "/t/site_content/edit?id=vision", data={"value": "{not json"}
    )
    assert resp.status_code == 400
    rows = {c.key: c.value for c in load_site_yaml(paths["site"])}
    assert rows["vision"]["text"] == "Our vision."  # unchanged
