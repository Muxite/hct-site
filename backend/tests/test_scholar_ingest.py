"""Tests for ScholarIngestor — ujin chunk events -> Supabase (LLM faked)."""

from __future__ import annotations

import json

from src.scholar_ingest import ScholarIngestor, chunk_text


class FakeLLM:
    def __init__(self, by_text):
        self.by_text = by_text
        self.calls = 0

    def complete(self, *, system, user, **kw):
        self.calls += 1
        for needle, pubs in self.by_text.items():
            if needle in user:
                return json.dumps({"publications": pubs})
        return json.dumps({"publications": []})


class FakeSupabase:
    """Emulates slug-keyed upsert + full replace, recording calls."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.upserts: list[tuple[str, int]] = []
        self.replaces: list[tuple[str, int]] = []

    def upsert(self, table, rows, *, on_conflict=None):
        self.upserts.append((table, len(rows)))
        by = {r["slug"]: r for r in self.tables.get(table, [])}
        for r in rows:
            by[r["slug"]] = r
        self.tables[table] = list(by.values())
        return len(rows)

    def replace(self, table, rows, *, key):
        self.replaces.append((table, len(rows)))
        self.tables[table] = list(rows)
        return len(rows)


ALPHA = {"title": "Alpha paper", "authors": ["N Ashjaee"], "year": 2026, "type": "article"}
BETA = {"title": "Beta study", "authors": ["S Fels"], "year": 2024, "type": "inproceedings"}


def _event(idx, total, rows):
    return {"job_id": "scholar-x", "chunk_index": idx, "chunk_total": total,
            "payload": [{"text": t, "href": None} for t in rows]}


def test_chunk_text_flattens_and_skips_empty():
    assert chunk_text([{"text": "a"}, {"text": "  "}, {"text": "b"}]) == "a\n\nb"
    assert chunk_text("raw html blob") == "raw html blob"
    assert chunk_text(None) == ""


def test_handle_extracts_upserts_and_builds_timeline():
    llm = FakeLLM({"Alpha": [ALPHA]})
    sb = FakeSupabase()
    ing = ScholarIngestor(llm=llm, supabase=sb)
    summary = ing.handle(_event(0, 2, ["Alpha paper by N Ashjaee, 2026"]))
    assert summary["written"] == 1 and summary["total"] == 1
    assert sb.tables["publications"][0]["title"] == "Alpha paper"
    assert ("publications", 1) in sb.upserts
    assert sb.tables["timeline"]  # rebuilt from the chunk


def test_accumulates_across_chunks_then_resets_on_chunk0():
    llm = FakeLLM({"Alpha": [ALPHA], "Beta": [BETA]})
    sb = FakeSupabase()
    ing = ScholarIngestor(llm=llm, supabase=sb)
    ing.handle(_event(0, 2, ["Alpha paper, 2026"]))
    s2 = ing.handle(_event(1, 2, ["Beta study, 2024"]))
    assert s2["total"] == 2
    assert len(sb.tables["publications"]) == 2
    # timeline rebuilt from the union, newest year first
    assert sb.tables["timeline"][0]["year"] == 2026
    # a new harvest (chunk_index 0 again) resets the accumulator
    s3 = ing.handle(_event(0, 2, ["Alpha paper, 2026"]))
    assert s3["total"] == 1


def test_empty_chunk_writes_nothing():
    llm = FakeLLM({})
    sb = FakeSupabase()
    ing = ScholarIngestor(llm=llm, supabase=sb)
    summary = ing.handle(_event(0, 1, []))
    assert summary["written"] == 0
    assert llm.calls == 0
    assert sb.upserts == []
