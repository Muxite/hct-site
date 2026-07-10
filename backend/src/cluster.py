"""One-shot AI clustering: propose which papers belong to which featured project.

See docs/PROJECTS.md. This is deterministic-first in spirit: the LLM only
*proposes* membership from title/year/venue (no full text, so one batched call
covers the whole publication history cheaply); the operator reviews and edits
the resulting ``projects.yaml`` before ``sync-content`` ever writes to
Supabase. Conservative by design — a paper left unassigned just stays in the
plain timeline, which is always safe, so the prompt is told to skip anything
ambiguous rather than guess.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from src.models import Publication

_SYSTEM = (
    "You sort a research lab's publication list into its named ongoing research "
    "projects, using only each paper's title, year, and venue. For every "
    "project, pick only the papers that clearly and confidently belong to it — "
    "skip anything ambiguous, tangential, or where you are unsure; it is normal "
    "and expected for most papers to be assigned to no project at all. Never "
    "invent a paper slug that was not given to you. Return at most "
    "{max_per_project} papers per project, favoring the clearest and most "
    "recent matches. Respond with strict JSON: "
    '{{"assignments": {{"<project_slug>": ["<paper_slug>", ...], ...}}}}'
)


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def build_cluster_prompt(
    pubs: list[Publication], projects: list[dict[str, str]]
) -> str:
    """Build the user prompt: candidate projects, then the paper list.

    :param pubs: publications to sort (only slug/title/year/venue are used).
    :param projects: ``[{"slug": ..., "title": ..., "tagline": ...}, ...]``.
    """

    proj_lines = "\n".join(
        f"- {p['slug']}: {p['title']}" + (f" — {p['tagline']}" if p.get("tagline") else "")
        for p in projects
    )
    paper_lines = "\n".join(
        f"{pub.id} | {pub.year} | {pub.venue or ''} | {pub.title}" for pub in pubs
    )
    return (
        f"Projects:\n{proj_lines}\n\n"
        f"Papers (slug | year | venue | title):\n{paper_lines}"
    )


def parse_cluster_response(
    text: str, *, valid_projects: set[str], valid_papers: set[str]
) -> dict[str, list[str]]:
    """Parse+validate the LLM's JSON reply, dropping any unknown slug.

    Never trusts the model: a hallucinated project or paper slug is silently
    dropped rather than propagated into ``projects.yaml``.
    """

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"cluster response was not valid JSON: {exc}") from exc
    raw = data.get("assignments", {})
    if not isinstance(raw, dict):
        raise ValueError("cluster response 'assignments' must be an object")
    out: dict[str, list[str]] = {}
    for proj_slug, paper_slugs in raw.items():
        if proj_slug not in valid_projects or not isinstance(paper_slugs, list):
            continue
        seen: list[str] = []
        for slug in paper_slugs:
            if isinstance(slug, str) and slug in valid_papers and slug not in seen:
                seen.append(slug)
        if seen:
            out[proj_slug] = seen
    return out


def cluster_projects(
    pubs: list[Publication],
    projects: list[dict[str, str]],
    llm: SupportsComplete,
    *,
    max_per_project: int = 15,
) -> dict[str, list[str]]:
    """Ask the LLM to assign papers to projects in a single call.

    Returns ``{project_slug: [paper_slug, ...]}``; projects with no confident
    match are simply absent from the result.
    """

    valid_projects = {p["slug"] for p in projects}
    valid_papers = {pub.id for pub in pubs}
    user = build_cluster_prompt(pubs, projects)
    text = llm.complete(
        system=_SYSTEM.format(max_per_project=max_per_project),
        user=user,
        label="cluster",
    )
    return parse_cluster_response(text, valid_projects=valid_projects, valid_papers=valid_papers)
