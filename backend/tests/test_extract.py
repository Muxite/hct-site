"""Unit tests for LLM-driven extraction (LLM is faked — no network)."""

from __future__ import annotations

import json

import pytest

from src.extract import (
    ExtractionError,
    _extract_json_object,
    build_user_prompt,
    extract_publications,
    parse_publication_set,
)


class FakeLLM:
    """Returns queued responses; records the prompts it was given."""

    def __init__(self, *responses: str):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, system, user, **kw):
        self.calls.append({"system": system, "user": user})
        return self._responses.pop(0)


GOOD = json.dumps(
    {
        "publications": [
            {
                "title": "A unified representation",
                "authors": ["Hongzhi Zhu", "Sidney Fels"],
                "year": 2022,
                "type": "article",
                "venue": "IEEE JBHI",
                "link": "https://doi.org/10.1109/JBHI.2022.3150242",
            },
            {
                "title": "Older work",
                "authors": ["A Person"],
                "year": 2019,
                "type": "preprint",
            },
        ]
    }
)


def test_extract_json_object_handles_fences_and_prose():
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('here you go: {"a": 2} thanks') == {"a": 2}
    assert _extract_json_object('{"a": 3}') == {"a": 3}


def test_parse_computes_ids_and_validates():
    ps = parse_publication_set(GOOD)
    assert [p.id for p in ps.publications] == [
        "zhu2022-a-unified-representation",
        "person2019-older-work",
    ]
    assert ps.publications[0].type.value == "article"


def test_parse_dedupes_identical_ids():
    dup = json.dumps(
        {
            "publications": [
                {"title": "X", "authors": ["A B"], "year": 2020, "type": "misc"},
                {"title": "X", "authors": ["A B"], "year": 2020, "type": "misc"},
            ]
        }
    )
    ps = parse_publication_set(dup)
    assert len(ps.publications) == 1


def test_parse_carries_fingerprints():
    ps = parse_publication_set(GOOD, fingerprints={"fels": "fp1"})
    assert ps.source_fingerprints == {"fels": "fp1"}


def test_extract_happy_path_single_call():
    llm = FakeLLM(GOOD)
    ps = extract_publications("page text", llm=llm)
    assert len(ps.publications) == 2
    assert len(llm.calls) == 1


def test_extract_repairs_after_bad_output():
    llm = FakeLLM("not json at all", GOOD)
    ps = extract_publications("the full page text here", llm=llm)
    assert len(ps.publications) == 2
    assert len(llm.calls) == 2
    # repair prompt feeds back the bad output + error...
    assert "could not be used" in llm.calls[1]["user"]
    assert "not json at all" in llm.calls[1]["user"]
    # ...but does NOT resend the page text (token-saving guard)
    assert "the full page text here" not in llm.calls[1]["user"]


def test_extract_raises_after_failed_repair():
    llm = FakeLLM("garbage", "still garbage")
    with pytest.raises(ExtractionError):
        extract_publications("page text", llm=llm)
    assert len(llm.calls) == 2


def test_extract_repairs_on_validation_error():
    bad = json.dumps({"publications": [{"title": "X", "authors": [], "year": 2020}]})
    llm = FakeLLM(bad, GOOD)  # empty authors fails validation -> repair
    ps = extract_publications("page text", llm=llm)
    assert len(ps.publications) == 2
    assert len(llm.calls) == 2


def test_build_user_prompt_includes_examples_and_page():
    prompt = build_user_prompt("PAGE", examples="EX1")
    assert "EX1" in prompt
    assert "PAGE" in prompt


def test_build_user_prompt_caps_page_text():
    big = "x" * 50_000
    prompt = build_user_prompt(big, max_page_chars=1000)
    # the page span between the markers is truncated to exactly the cap
    page = prompt.split("<<<PAGE>>>\n", 1)[1].split("\n<<<END>>>", 1)[0]
    assert page == "x" * 1000
    assert len(prompt) < 1500
