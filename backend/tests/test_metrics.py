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


def test_cost_breakdown_itemizes_input_and_output():
    b = metrics.cost_breakdown("google/gemini-3-flash-preview", 1_000_000, 1_000_000)
    assert round(b["input_cost_usd"], 4) == 0.5    # 1M prompt tokens * 0.5e-6
    assert round(b["output_cost_usd"], 4) == 3.0   # 1M completion tokens * 3.0e-6
    assert b["total_cost_usd"] == b["input_cost_usd"] + b["output_cost_usd"]
    # total matches the scalar estimate_cost for the same inputs
    assert round(b["total_cost_usd"], 6) == round(
        metrics.estimate_cost("google/gemini-3-flash-preview", 1_000_000, 1_000_000), 6
    )


def test_cost_breakdown_unknown_model_is_zero():
    b = metrics.cost_breakdown("mystery/model", 1000, 1000)
    assert b == {"input_cost_usd": 0.0, "output_cost_usd": 0.0, "total_cost_usd": 0.0}


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


# --------------------------------------------------------------------------- #
# ParseTracker

from src.cv_parse import ParseOutcome  # noqa: E402


def _outcomes():
    return [
        ParseOutcome(path="deterministic", section="journal", slug="a2020-x",
                     entry_preview="A..."),
        ParseOutcome(path="deterministic", section="conference", slug="b2021-y",
                     entry_preview="B..."),
        ParseOutcome(path="llm", section="journal", slug="c2022-z",
                     failed_fields=["authors"], entry_preview="C..."),
        ParseOutcome(path="failed", section="other", failed_fields=["year", "title"],
                     entry_preview="D...", error="deterministic parse failed: year, title"),
    ]


def test_parse_tracker_summary_counts():
    t = metrics.ParseTracker()
    for o in _outcomes():
        t.record(o)
    s = t.summary
    assert s["total"] == 4
    assert s["deterministic"] == 2
    assert s["llm"] == 1
    assert s["failed"] == 1
    assert s["det_rate"] == 0.5
    assert s["by_section"]["journal"] == {"deterministic": 1, "llm": 1, "failed": 0}
    assert s["by_section"]["other"]["failed"] == 1
    assert s["field_failures"] == {"authors": 1, "year": 1, "title": 1}


def test_parse_tracker_empty_summary():
    t = metrics.ParseTracker()
    assert t.summary["total"] == 0
    assert t.summary["det_rate"] == 0.0
    assert "no entries" in t.render()


def test_parse_tracker_dump_jsonl_appends(tmp_path):
    t = metrics.ParseTracker()
    for o in _outcomes():
        t.record(o)
    path = tmp_path / "parse-report.jsonl"
    t.dump_jsonl(path)
    t.dump_jsonl(path)
    rows = metrics.load_records(path)
    assert len(rows) == 8
    assert rows[0]["path"] == "deterministic" and rows[0]["section"] == "journal"
    assert rows[3]["failed_fields"] == ["year", "title"]
    assert rows[0]["ts"]


def test_parse_tracker_dump_summary(tmp_path):
    t = metrics.ParseTracker(label="run-1")
    for o in _outcomes():
        t.record(o)
    path = tmp_path / "parse-summary.jsonl"
    t.dump_summary(path)
    t.dump_summary(path)
    rows = metrics.load_records(path)
    assert len(rows) == 2
    assert rows[0]["label"] == "run-1"
    assert rows[0]["total"] == 4 and rows[0]["det_rate"] == 0.5
    assert rows[0]["ts"]


def test_parse_tracker_render_table():
    t = metrics.ParseTracker()
    for o in _outcomes():
        t.record(o)
    out = t.render()
    assert "4 entries" in out
    assert "2 deterministic (50%)" in out
    assert "1 via LLM fallback" in out
    assert "journal" in out and "other" in out
    assert "field failures:" in out and "authors=1" in out
