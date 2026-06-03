"""Unit tests for the token/latency metrics tracker."""

from __future__ import annotations

from src import metrics


def test_record_and_totals():
    t = metrics.UsageTracker(label="agent")
    t.record(model="google/gemini-3-flash-preview",
             usage={"prompt_tokens": 100, "completion_tokens": 20}, latency_s=1.5, label="extract")
    t.record(model="google/gemini-3-flash-preview",
             usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}, latency_s=0.5)
    tot = t.totals
    assert tot["calls"] == 2
    assert tot["prompt_tokens"] == 150
    assert tot["completion_tokens"] == 30
    # first record derives total (100+20=120), second uses explicit 60 -> 180
    assert tot["total_tokens"] == 180
    assert tot["latency_s"] == 2.0
    assert tot["cost_usd"] > 0


def test_estimate_cost_known_model():
    cost = metrics.estimate_cost("google/gemini-3-flash-preview", 1_000_000, 1_000_000)
    assert round(cost, 2) == round(0.5 + 3.0, 2)


def test_estimate_cost_unknown_model_is_zero():
    assert metrics.estimate_cost("mystery/model", 1000, 1000) == 0.0


def test_dump_and_load_roundtrip(tmp_path):
    t = metrics.UsageTracker()
    t.record(model="m", usage={"prompt_tokens": 5, "completion_tokens": 5}, latency_s=0.1, label="x")
    path = tmp_path / "metrics.jsonl"
    t.dump_jsonl(path)
    t.dump_jsonl(path)  # append, not overwrite
    rows = metrics.load_records(path)
    assert len(rows) == 2
    assert rows[0]["label"] == "x" and rows[0]["total_tokens"] == 10


def test_load_missing_file_is_empty(tmp_path):
    assert metrics.load_records(tmp_path / "nope.jsonl") == []
