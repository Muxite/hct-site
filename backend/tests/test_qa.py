"""Unit tests for the data QA checks and the plain-text report (no network)."""

from __future__ import annotations

from src import qa


def _refs(findings, *, category=None, severity=None, table=None):
    """Helper: the set of refs among findings matching the given filters."""
    out = set()
    for f in findings:
        if category and f.category != category:
            continue
        if severity and f.severity != severity:
            continue
        if table and f.table != table:
            continue
        out.add(f.ref)
    return out


def _good_pub(**over):
    row = {
        "slug": "zhu2022-unified",
        "title": "A unified representation of control logic",
        "authors": ["Hongzhi Zhu", "Sidney Fels"],
        "year": 2022,
        "type": "article",
        "venue": "IEEE JBHI",
        "link": "https://doi.org/10.1109/x",
        "description": "A clear two-sentence summary of the contribution. It explains why the work matters.",
    }
    row.update(over)
    return row


# --- schema & consistency --------------------------------------------------
def test_schema_flags_invalid_publication():
    rows = {"publications": [_good_pub(year=3000)]}  # out of bounds -> Pydantic error
    findings = list(qa._schema_checks(rows))
    assert _refs(findings, category="schema", severity=qa.ERROR)


def test_schema_flags_duplicate_slug():
    rows = {"publications": [_good_pub(), _good_pub()]}
    msgs = [f.message for f in qa._schema_checks(rows)]
    assert any("duplicate slug" in m for m in msgs)


def test_schema_bad_link_is_error():
    rows = {"publications": [_good_pub(link="ftp://nope")]}
    assert any(f.severity == qa.ERROR for f in qa._schema_checks(rows))


def test_timeline_dangling_slug_is_error():
    rows = {
        "publications": [_good_pub(slug="a")],
        "timeline": [{"slug": "ghost", "title": "x", "position": 0, "blurb": "hi there friend"}],
    }
    errs = [f for f in qa._schema_checks(rows) if f.severity == qa.ERROR and f.table == "timeline"]
    assert errs and "no matching publication" in errs[0].message


def test_timeline_count_mismatch_warns():
    # Timeline should mirror the full publication history (one entry per paper).
    rows = {
        "publications": [_good_pub(slug="a"), _good_pub(slug="b")],
        "timeline": [{"slug": "a", "title": "x", "position": 0}],
    }
    warns = [f for f in qa._schema_checks(rows) if f.severity == qa.WARN]
    assert any("expected one per paper" in f.message for f in warns)


def test_timeline_full_history_no_count_warning():
    rows = {
        "publications": [_good_pub(slug="a"), _good_pub(slug="b")],
        "timeline": [
            {"slug": "a", "title": "x", "position": 0},
            {"slug": "b", "title": "y", "position": 1},
        ],
    }
    warns = [f for f in qa._schema_checks(rows) if f.severity == qa.WARN]
    assert not any("expected one per paper" in f.message for f in warns)


# --- completeness ----------------------------------------------------------
def test_completeness_missing_description():
    rows = {"publications": [_good_pub(description=None)]}
    assert "zhu2022-unified" in _refs(
        qa._completeness_checks(rows), category="completeness", table="publications"
    )


def test_completeness_missing_site_content_key():
    rows = {"site_content": [{"key": "vision", "value": {}}]}
    refs = _refs(qa._completeness_checks(rows), table="site_content")
    assert "contact" in refs and "vision" not in refs


def test_completeness_people_no_bio():
    rows = {"people": [{"name": "Jane Doe", "role": "PhD", "email": "j@x", "photo": "p.png"}]}
    warns = [f for f in qa._completeness_checks(rows) if f.severity == qa.WARN]
    assert any(f.ref == "Jane Doe" and "bio" in f.message for f in warns)


# --- AI-writing sanity -----------------------------------------------------
def test_ai_flags_filler_phrase():
    rows = {"publications": [_good_pub(description="This paper is great and we delve into things deeply here.")]}
    msgs = [f.message for f in qa._ai_checks(rows)]
    assert any("filler" in m for m in msgs)


def test_ai_flags_too_long():
    rows = {"publications": [_good_pub(description="word " * 200)]}
    assert any("very long" in f.message for f in qa._ai_checks(rows))


def test_ai_flags_too_short():
    rows = {"publications": [_good_pub(description="Short.")]}
    assert any("very short" in f.message for f in qa._ai_checks(rows))


def test_ai_flags_markdown_and_numbers():
    rows = {"timeline": [{
        "position": 0, "slug": "a", "title": "T",
        "blurb": "We improved accuracy by 30% using **bold** tricks across the board here today.",
    }]}
    msgs = [f.message for f in qa._ai_checks(rows)]
    assert any("markdown" in m for m in msgs)
    assert any("numeric" in m for m in msgs)


def test_ai_flags_echoed_title():
    title = "A unified representation of control logic"
    rows = {"publications": [_good_pub(description=f"{title} is what this introduces for readers everywhere.")]}
    assert any("echoed" in f.message for f in qa._ai_checks(rows))


def test_ai_skips_blank_prose():
    rows = {"publications": [_good_pub(description=None)]}
    assert list(qa._ai_checks(rows)) == []


# --- source cross-check ----------------------------------------------------
def test_source_flags_publication_not_on_page():
    src = qa.StaticSource(pub_text="some unrelated text about other papers")
    rows = {"publications": [_good_pub()]}
    findings = list(qa._source_checks(rows, src))
    assert any("not found in static page" in f.message for f in findings)


def test_source_matches_publication_on_page():
    src = qa.StaticSource(pub_text="a unified representation of control logic, zhu 2022")
    rows = {"publications": [_good_pub()]}
    assert list(qa._source_checks(rows, src)) == []


def test_source_flags_person_not_in_yaml():
    src = qa.StaticSource(people_names=["Sidney Fels"])
    rows = {"people": [{"name": "Ghost Person"}]}
    findings = list(qa._source_checks(rows, src))
    assert any(f.table == "people" and "not in people.yaml" in f.message for f in findings)


# --- aggregation + report --------------------------------------------------
def test_run_qa_exit_code_and_strict():
    clean = {"publications": [_good_pub()]}
    rep = qa.run_qa(clean)
    assert rep.n_errors == 0
    assert rep.exit_code == 0
    # A clean pub still has nothing wrong, but force a warning via strict.
    rep_warn = qa.run_qa({"publications": [_good_pub(description=None)]})
    assert rep_warn.n_warnings >= 1 and rep_warn.exit_code == 0
    rep_strict = qa.run_qa({"publications": [_good_pub(description=None)]}, strict=True)
    assert rep_strict.exit_code == 1

    rep_err = qa.run_qa({"publications": [_good_pub(), _good_pub()]})
    assert rep_err.n_errors >= 1 and rep_err.exit_code == 1


def test_report_render_has_summary_and_status():
    rep = qa.run_qa({"publications": [_good_pub(), _good_pub()]}, source_url="https://x.supabase.co")
    text = rep.render()
    assert "DATA QA REPORT" in text
    assert "SUMMARY" in text
    assert "STATUS: FAIL" in text
    assert "https://x.supabase.co" in text
    assert "SCHEMA & CONSISTENCY" in text


def test_build_source_combines_static_pubs_and_yaml_names():
    html = '<main><div id="publications-static">A unified representation of control logic</div></main>'
    src = qa.build_source(html, people_names=["Sidney Fels"])
    assert "Sidney Fels" in src.people_names
    assert "control logic" in src.pub_text


def test_build_source_without_names_skips_people_checks():
    src = qa.build_source("<main></main>")
    assert src.people_names == []
