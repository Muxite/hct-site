"""Unit tests for static-HTML content parsing + AI enrichment (LLM faked)."""

from __future__ import annotations

from src.content import (
    build_content,
    enrich_research,
    parse_people,
    parse_research,
    parse_site_sections,
    publications_block_text,
)

SAMPLE = """
<h2>People</h2>
<div id="people" class="wrapper"><div class="person-tile">
  <div class="photo"><img alt="Sid" src="sid.png"></div>
  <div class="info">
    <strong>Prof. Sid Fels</strong>
    <div class="project" style="white-space: nowrap">Director, HCT Lab</div>
    <div class="email"><a href="mailto">ssfels [at] ece.ubc.ca</a></div>
  </div>
<br></div><div class="person-tile">
  <div class="photo"><img alt="Nima" src="nima.jpg"></div>
  <div class="info">
    <strong> Nima Ashjaee</strong>
    <div class="project">PhD Student</div>
    <div class="email"><a href="mailto">nima [at] ubc.ca</a></div>
  </div>
<br></div></div>

<h2>Research</h2>
<div id="research" class="wrapper"><a class="research-tile" href="https://x/brain2speech/">
  <div class="photo"><img alt="B2S" src="b2s.png"></div>
  <div class="info"><h3>Brain2Speech</h3><h4 class="">BCI speech synthesis</h4></div>
</a><a class="research-tile" href="https://x/mr/">
  <div class="photo"><img alt="MR" src="mr.png"></div>
  <div class="info"><h3>Mixed Reality</h3><h4 class=""></h4></div>
</a></div>

<h2>Vision</h2>
<div>Our vision is effective human communication.</div>

<h2>Contact</h2>
<strong>HCT Lab</strong>
<div>2366 Main Mall</div>
"""


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, *, system, user, **kw):
        self.calls += 1
        return f"desc-{self.calls}"


def test_parse_people():
    people = parse_people(SAMPLE)
    assert [p.name for p in people] == ["Prof. Sid Fels", "Nima Ashjaee"]
    assert people[0].role == "Director, HCT Lab"
    assert people[0].email == "ssfels@ece.ubc.ca"  # " [at] " -> "@"
    assert people[0].photo == "sid.png"
    assert people[0].sort_order == 0
    assert people[1].sort_order == 1


def test_parse_research():
    research = parse_research(SAMPLE)
    assert [r.title for r in research] == ["Brain2Speech", "Mixed Reality"]
    assert research[0].tagline == "BCI speech synthesis"
    assert research[0].link == "https://x/brain2speech/"
    assert research[0].image == "b2s.png"
    assert research[1].tagline is None  # empty <h4>


def test_parse_site_sections():
    content = {c.key: c.value for c in parse_site_sections(SAMPLE)}
    assert "vision" in content and "contact" in content
    assert "effective human communication" in content["vision"]["text"]
    assert content["vision"]["title"] == "Vision"
    # structured sections are not captured as prose
    assert "people" not in content and "research" not in content


def test_enrich_research_fills_descriptions():
    research = parse_research(SAMPLE)
    llm = FakeLLM()
    enrich_research(research, llm=llm, style_profile="terse")
    assert all(r.description and r.description.startswith("desc-") for r in research)
    assert llm.calls == 2


def test_build_content_with_llm():
    people, research, site = build_content(SAMPLE, llm=FakeLLM())
    assert len(people) == 2
    assert all(r.description for r in research)
    assert {c.key for c in site} >= {"vision", "contact"}


def test_build_content_without_llm_skips_enrichment():
    people, research, site = build_content(SAMPLE)
    assert all(r.description is None for r in research)


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


def test_publications_block_text_inlines_link_hrefs():
    # The DOI lives in href, not the link text — it must survive into the text
    # so the LLM can extract it (otherwise every paper gets link=null).
    html = (
        '<main><div id="publications-static"><div>'
        "<strong>A Paper</strong>"
        '<a href="https://doi.org/10.1/x">link</a></div></div></main>'
    )
    text = publications_block_text(html)
    assert "https://doi.org/10.1/x" in text
