"""Unit tests for site.yaml loading and the legacy HTML prose helpers."""

from __future__ import annotations

import pytest

from src.content import (
    SiteContentError,
    dump_site_yaml,
    load_site_yaml,
    parse_site_sections,
    publications_block_text,
)

SAMPLE = """
<h2>People</h2>
<div id="people" class="wrapper"><div class="person-tile">
  <strong>Prof. Sid Fels</strong>
</div></div>

<h2>Research</h2>
<div id="research" class="wrapper"><a class="research-tile" href="https://x/brain2speech/">
  <h3>Brain2Speech</h3>
</a></div>

<h2>Vision</h2>
<div>Our vision is effective human communication.</div>

<h2>Contact</h2>
<strong>HCT Lab</strong>
<div>2366 Main Mall</div>
"""


def test_parse_site_sections():
    content = {c.key: c.value for c in parse_site_sections(SAMPLE)}
    assert "vision" in content and "contact" in content
    assert "effective human communication" in content["vision"]["text"]
    assert content["vision"]["title"] == "Vision"
    # structured sections are not captured as prose
    assert "people" not in content and "research" not in content


def test_publications_block_text_extracts_static_block():
    html = (
        '<main><h2 id="publications">Publications</h2>'
        '<div id="publications-list" hidden></div>'
        '<div id="publications-static">'
        "<div><strong>A Recent Paper</strong></div>"
        "<div>2022. [Article]</div></div></main>"
        "<script>ignored()</script>"
    )
    text = publications_block_text(html)
    assert "A Recent Paper" in text
    assert "2022" in text
    assert "ignored" not in text  # stops at </main>, scripts dropped


def test_publications_block_text_missing_returns_empty():
    assert publications_block_text("<main>no static block</main>") == ""


SITE_YAML = """
site:
  title: HCT Lab
  subtitle: Human Communication Technologies Lab
  tagline: Effective communication of human experience.
  nav: [Latest, Vision, People]
sections:
  vision:
    title: Vision
    text: Our vision is effective human communication.
  contact:
    title: Contact
    text: |
      HCT Lab
      2366 Main Mall
"""


def test_load_site_yaml_emits_meta_and_sections(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text(SITE_YAML, encoding="utf-8")
    rows = {c.key: c.value for c in load_site_yaml(p)}

    assert rows["site_meta"]["title"] == "HCT Lab"
    assert rows["site_meta"]["nav"] == ["Latest", "Vision", "People"]
    assert rows["vision"]["title"] == "Vision"
    assert "effective human communication" in rows["vision"]["text"]
    assert "2366 Main Mall" in rows["contact"]["text"]


def test_load_site_yaml_missing_file(tmp_path):
    with pytest.raises(SiteContentError):
        load_site_yaml(tmp_path / "nope.yaml")


def test_load_site_yaml_empty_section_text_fails(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text("sections:\n  vision:\n    title: Vision\n    text: ''\n", encoding="utf-8")
    with pytest.raises(SiteContentError):
        load_site_yaml(p)


def test_load_site_yaml_sections_only(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text("sections:\n  vision:\n    title: V\n    text: Some text.\n", encoding="utf-8")
    rows = {c.key: c.value for c in load_site_yaml(p)}
    assert set(rows) == {"vision"}


def test_site_yaml_round_trip(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text("# site header — keep me\n" + SITE_YAML, encoding="utf-8")
    before = {c.key: c.value for c in load_site_yaml(p)}
    dump_site_yaml(p, load_site_yaml(p))
    after = {c.key: c.value for c in load_site_yaml(p)}
    assert after == before
    assert p.read_text(encoding="utf-8").startswith("# site header — keep me\n")


def test_publications_block_text_inlines_link_hrefs():
    # The DOI lives in href, not the link text — it must survive into the text
    # so the QA cross-check can see it.
    html = (
        '<main><div id="publications-static"><div>'
        "<strong>A Paper</strong>"
        '<a href="https://doi.org/10.1/x">link</a></div></div></main>'
    )
    text = publications_block_text(html)
    assert "https://doi.org/10.1/x" in text
