"""Unit tests for environment-driven configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import DEFAULT_MODEL, Config


def test_from_env_requires_api_key():
    with pytest.raises(RuntimeError):
        Config.from_env({})


def test_from_env_defaults():
    cfg = Config.from_env({"OPENROUTER_API_KEY": "k"})
    assert cfg.openrouter_api_key == "k"
    assert cfg.model == DEFAULT_MODEL
    assert cfg.scrape_mode == "article"
    assert cfg.ujin_url.endswith(":8901")


def test_from_env_overrides():
    cfg = Config.from_env(
        {
            "OPENROUTER_API_KEY": "k",
            "OPENROUTER_MODEL": "anthropic/claude-3.7",
            "UJIN_URL": "http://localhost:9000",
            "HCT_DATA_DIR": "/data/assets",
            "HCT_SCRAPE_MODE": "links",
        }
    )
    assert cfg.model == "anthropic/claude-3.7"
    assert cfg.ujin_url == "http://localhost:9000"
    assert cfg.data_dir == Path("/data/assets")
    assert cfg.scrape_mode == "links"


def test_from_env_reads_supabase_keys():
    cfg = Config.from_env(
        {
            "OPENROUTER_API_KEY": "k",
            "SB_URL": "https://proj.supabase.co/",
            "SB_SEC_KEY": "secret",
            "SB_PUB_KEY": "publishable",
        }
    )
    assert cfg.sb_url == "https://proj.supabase.co"  # trailing slash trimmed
    assert cfg.sb_secret_key == "secret"
    assert cfg.sb_publishable_key == "publishable"


def test_supabase_key_legacy_fallbacks():
    cfg = Config.from_env(
        {
            "OPENROUTER_API_KEY": "k",
            "SB_SERVICE_ROLE_KEY": "legacy-service",
            "SB_ANON_PUB_KEY": "legacy-anon",
        }
    )
    assert cfg.sb_secret_key == "legacy-service"
    assert cfg.sb_publishable_key == "legacy-anon"


def test_derived_paths_follow_data_dir():
    cfg = Config.from_env({"OPENROUTER_API_KEY": "k", "HCT_DATA_DIR": "/a"})
    assert cfg.templates_dir == Path("/a/templates")
    assert cfg.state_dir == Path("/a/state")
    assert cfg.sources_file == Path("/a/sources/sources.yaml")
    assert cfg.examples_dir == Path("/a/examples")
    assert cfg.inputs_dir == Path("/a/inputs")
