"""hct ujin plugins: a Scholar-profile source + a Supabase publications sink.

Mount this directory as ujin's ``UJIN_PLUGINS_DIR`` and run the jobs service with
hct's ``src`` package importable and the usual env set (``OPENROUTER_API_KEY``,
``SB_URL``, ``SB_SEC_KEY``). Two kinds become available:

* ``plugin:scholar_profile`` (source) — a ``browser`` source pre-wired for Google
  Scholar: clicks "Show more" (``#gsc_bpf_more``) until the profile is fully
  loaded, harvesting each row (``.gsc_a_tr``) as text. Keeps all Scholar-specific
  selectors here in hct, not in ujin core. Config: ``user`` (Scholar id) or a full
  ``url``; optional ``hl``, ``max_clicks``, ``timeout_ms``, ``engine``, ``headless``.

* ``plugin:hct_publications`` (sink) — extracts each chunk's rows with the LLM and
  upserts validated publications (+ rebuilds the timeline) to Supabase, via
  :class:`src.scholar_ingest.ScholarIngestor`.

Wire them together with a ``chunk`` transform (size 20). See
``backend/jobs/scholar.yaml``. This code runs in-process in ujin with no sandbox.
"""
from __future__ import annotations

import asyncio
import logging

from ujin import register

log = logging.getLogger("ujin.plugins.hct")

# Google Scholar citations-profile selectors (live here, not in ujin core).
_SHOW_MORE_BUTTON = "#gsc_bpf_more"   # the "Show more" button
_ROW = ".gsc_a_tr"                    # one publication row (title + authors + venue + year)
_TABLE_BODY = "#gsc_a_b"             # the publications table body


@register.source("scholar_profile")
def make_scholar_source(cfg: dict, ctx):
    """Browser source pre-configured to fully load a Scholar profile."""

    from ujin.poll.browser import BrowserPollable

    url = cfg.get("url")
    if not url:
        user = cfg.get("user")
        if not user:
            raise ValueError("scholar_profile source needs 'user' (Scholar id) or 'url'")
        hl = cfg.get("hl", "en")
        url = (
            f"https://scholar.google.com/citations?user={user}&hl={hl}"
            "&view_op=list_works&sortby=pubdate&pagesize=100"
        )
    actions = [
        {"action": "wait_for_selector", "selector": _TABLE_BODY},
        {
            "action": "load_more",
            "button": _SHOW_MORE_BUTTON,
            "results": _ROW,
            "max_clicks": int(cfg.get("max_clicks", 200)),
            "timeout_ms": int(cfg.get("timeout_ms", 180000)),
        },
    ]
    return BrowserPollable(
        url,
        engine=cfg.get("engine", "playwright"),
        actions=actions,
        extract="raw",
        results_selector=_ROW,
        headless=cfg.get("headless", True),
        ctx=ctx,
    )


@register.sink("hct_publications")
def make_publications_sink(cfg: dict):
    """Sink: extract each chunk of Scholar rows and upsert to Supabase.

    Builds the LLM + Supabase clients from the environment (``Config.from_env``)
    once, then reuses one :class:`ScholarIngestor` across the run's chunks so the
    timeline is rebuilt from the full accumulated set.
    """

    from src.config import Config
    from src.extract import load_system_prompt
    from src.llm import OpenRouterClient
    from src.scholar_ingest import ScholarIngestor
    from src.supabase_client import SupabaseClient

    env = Config.from_env()
    llm = OpenRouterClient(
        env.openrouter_api_key, model=env.model, base_url=env.openrouter_base_url
    )
    supabase = SupabaseClient(env.sb_url, env.sb_secret_key)
    ingestor = ScholarIngestor(
        llm=llm, supabase=supabase, system_prompt=load_system_prompt(env.templates_dir)
    )

    class _PublicationsSink:
        async def emit(self, event: dict) -> None:
            # Extraction + Supabase I/O are sync; keep them off the event loop.
            summary = await asyncio.to_thread(ingestor.handle, event)
            log.info(
                "hct_publications: job=%s chunk %s/%s wrote=%s total=%s",
                event.get("job_id"), summary.get("chunk_index"),
                summary.get("chunk_total"), summary.get("written"), summary.get("total"),
            )

    return _PublicationsSink()
