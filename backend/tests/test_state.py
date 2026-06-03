"""Unit tests for the fingerprint state store / change detection."""

from __future__ import annotations

import pytest

from src.state import StateStore, _safe_key


def test_first_seen_is_changed(tmp_path):
    s = StateStore(tmp_path)
    assert s.fingerprint("fels") is None
    assert s.changed("fels", "fp1") is True


def test_update_then_unchanged(tmp_path):
    s = StateStore(tmp_path)
    s.update("fels", "fp1", strategy="obscura")
    assert s.fingerprint("fels") == "fp1"
    assert s.changed("fels", "fp1") is False
    assert s.changed("fels", "fp2") is True


def test_update_persists_extra_metadata(tmp_path):
    s = StateStore(tmp_path)
    state = s.update("fels", "fp1", strategy="obscura", pub_count=12)
    assert state["strategy"] == "obscura"
    assert state["pub_count"] == 12
    assert "updated_at" in state
    # survives a fresh store instance
    assert StateStore(tmp_path).get("fels")["pub_count"] == 12


def test_empty_fingerprint_always_changed(tmp_path):
    s = StateStore(tmp_path)
    s.update("fels", "fp1")
    assert s.changed("fels", "") is True  # failed scrape never masks an update


def test_keys_are_isolated(tmp_path):
    s = StateStore(tmp_path)
    s.update("fels", "a")
    s.update("ashjaee", "b")
    assert s.fingerprint("fels") == "a"
    assert s.fingerprint("ashjaee") == "b"


def test_safe_key_sanitizes():
    assert _safe_key("Sidney Fels!") == "sidney-fels"
    assert _safe_key("  A/B..C  ") == "a-b-c"
    with pytest.raises(ValueError):
        _safe_key("***")


def test_atomic_update_no_temp_left(tmp_path):
    s = StateStore(tmp_path)
    s.update("fels", "fp1")
    assert list(tmp_path.glob("*.tmp")) == []
