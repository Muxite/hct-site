"""Unit tests for AI project clustering (LLM always mocked)."""

from __future__ import annotations

import json

import pytest

from src.cluster import build_cluster_prompt, cluster_projects, parse_cluster_response
from src.models import Publication

PROJECTS = [
    {"slug": "brain2speech", "title": "Brain2Speech", "tagline": "BCIs + speech synthesis"},
    {"slug": "videx", "title": "ViDeX", "tagline": "Video learning"},
]


def _pub(slug: str, title: str, year: int = 2023, venue: str = "Conf") -> Publication:
    return Publication(id=slug, title=title, authors=["A B"], year=year, type="paper", venue=venue)


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, **kw) -> str:
        self.calls.append({"system": system, "user": user, **kw})
        return self.reply


def test_build_cluster_prompt_lists_projects_then_papers():
    pubs = [_pub("a2023-x", "Paper X"), _pub("b2022-y", "Paper Y", year=2022)]
    prompt = build_cluster_prompt(pubs, PROJECTS)
    assert "brain2speech: Brain2Speech — BCIs + speech synthesis" in prompt
    assert "a2023-x | 2023 | Conf | Paper X" in prompt
    assert "b2022-y | 2022 | Conf | Paper Y" in prompt


def test_parse_cluster_response_drops_unknown_slugs():
    text = json.dumps(
        {
            "assignments": {
                "brain2speech": ["a2023-x", "hallucinated-slug"],
                "not-a-real-project": ["a2023-x"],
            }
        }
    )
    out = parse_cluster_response(
        text, valid_projects={"brain2speech", "videx"}, valid_papers={"a2023-x"}
    )
    assert out == {"brain2speech": ["a2023-x"]}


def test_parse_cluster_response_rejects_bad_json():
    with pytest.raises(ValueError):
        parse_cluster_response("not json", valid_projects=set(), valid_papers=set())


def test_parse_cluster_response_dedupes_and_ignores_non_list():
    text = json.dumps(
        {"assignments": {"brain2speech": ["a2023-x", "a2023-x"], "videx": "not-a-list"}}
    )
    out = parse_cluster_response(
        text, valid_projects={"brain2speech", "videx"}, valid_papers={"a2023-x"}
    )
    assert out == {"brain2speech": ["a2023-x"]}


def test_cluster_projects_calls_llm_once_and_validates():
    pubs = [_pub("a2023-x", "Paper X"), _pub("b2022-y", "Paper Y", year=2022)]
    reply = json.dumps({"assignments": {"brain2speech": ["a2023-x", "made-up"]}})
    llm = FakeLLM(reply)
    out = cluster_projects(pubs, PROJECTS, llm, max_per_project=5)
    assert out == {"brain2speech": ["a2023-x"]}
    assert len(llm.calls) == 1
    assert llm.calls[0]["label"] == "cluster"
    assert "at most 5 papers per project" in llm.calls[0]["system"]
