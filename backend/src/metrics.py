"""Lightweight metrics: LLM token/latency tracking + CV parse outcomes.

Every OpenRouter response carries a ``usage`` block; :class:`OpenRouterClient`
records one :class:`CallRecord` per call onto an optional :class:`UsageTracker`.
The tracker summarizes totals/cost and can append to a JSONL log
(``state/metrics.jsonl``) that the experimentation + plotting tools read back.

:class:`ParseTracker` is the same idea for the deterministic CV parser: one
:class:`ParseRecord` per publication entry (which path handled it, which
fields the heuristics couldn't fill, which CV section it sat in). Per-entry
records append to ``state/parse-report.jsonl`` and a one-line-per-run summary
to ``state/parse-summary.jsonl`` — the feedback loop for tuning heuristics.

Pure stdlib (no matplotlib here) so it imports cheaply everywhere; plotting
lives in the experiment tooling that opts into the heavy dependency.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Approx OpenRouter pricing, USD per token: (prompt, completion). Used only for
# rough cost lines in reports/plots — kept here so it's easy to update.
PRICING: dict[str, tuple[float, float]] = {
    "google/gemini-3-flash-preview": (0.5e-6, 3.0e-6),
    "google/gemini-3.1-flash-lite": (0.25e-6, 1.5e-6),
    "anthropic/claude-sonnet-4.6": (3.0e-6, 15.0e-6),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return prompt_tokens * pin + completion_tokens * pout


def cost_breakdown(model: str, prompt_tokens: int, completion_tokens: int) -> dict:
    """Split the cost into its input/output parts: the same number ``estimate_cost``
    returns, but itemized as ``input_tokens * input_price`` and
    ``output_tokens * output_price`` (so reports can show *where* the cost goes).
    """

    pin, pout = PRICING.get(model, (0.0, 0.0))
    input_cost = prompt_tokens * pin
    output_cost = completion_tokens * pout
    return {
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": input_cost + output_cost,
    }


@dataclass
class CallRecord:
    label: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    ok: bool = True
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def cost_usd(self) -> float:
        return estimate_cost(self.model, self.prompt_tokens, self.completion_tokens)


class UsageTracker:
    """Collects :class:`CallRecord`s across an agent run."""

    def __init__(self, label: str = "agent") -> None:
        self.label = label
        self.records: list[CallRecord] = []

    def record(
        self,
        *,
        model: str,
        usage: dict | None,
        latency_s: float,
        label: str | None = None,
        ok: bool = True,
    ) -> CallRecord:
        u = usage or {}
        prompt = int(u.get("prompt_tokens", 0) or 0)
        completion = int(u.get("completion_tokens", 0) or 0)
        total = int(u.get("total_tokens", 0) or 0) or (prompt + completion)
        rec = CallRecord(
            label=label or self.label,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            latency_s=round(latency_s, 4),
            ok=ok,
        )
        self.records.append(rec)
        return rec

    @property
    def totals(self) -> dict:
        return {
            "calls": len(self.records),
            "prompt_tokens": sum(r.prompt_tokens for r in self.records),
            "completion_tokens": sum(r.completion_tokens for r in self.records),
            "total_tokens": sum(r.total_tokens for r in self.records),
            "latency_s": round(sum(r.latency_s for r in self.records), 3),
            "cost_usd": round(sum(r.cost_usd for r in self.records), 6),
        }

    def dump_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(asdict(r)) + "\n")


@dataclass
class ParseRecord:
    """One CV entry's trip through deterministic parse (+ LLM fallback)."""

    section: str
    path: str  # "deterministic" | "llm" | "failed"
    slug: str | None = None
    failed_fields: list[str] = field(default_factory=list)
    entry_preview: str = ""
    error: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ParseTracker:
    """Collects :class:`ParseRecord`s across a CV extraction run."""

    def __init__(self, label: str = "cv-parse") -> None:
        self.label = label
        self.records: list[ParseRecord] = []

    def record(self, outcome) -> ParseRecord:
        """Record a ``cv_parse.ParseOutcome`` (anything with its fields)."""

        rec = ParseRecord(
            section=outcome.section,
            path=outcome.path,
            slug=outcome.slug,
            failed_fields=list(outcome.failed_fields),
            entry_preview=outcome.entry_preview,
            error=outcome.error,
        )
        self.records.append(rec)
        return rec

    @property
    def summary(self) -> dict:
        paths = ("deterministic", "llm", "failed")
        counts = {p: sum(1 for r in self.records if r.path == p) for p in paths}
        by_section: dict[str, dict[str, int]] = {}
        for r in self.records:
            by_section.setdefault(r.section, dict.fromkeys(paths, 0))[r.path] += 1
        field_failures: dict[str, int] = {}
        for r in self.records:
            for f in r.failed_fields:
                field_failures[f] = field_failures.get(f, 0) + 1
        total = len(self.records)
        return {
            "label": self.label,
            "total": total,
            **counts,
            "det_rate": round(counts["deterministic"] / total, 4) if total else 0.0,
            "by_section": by_section,
            "field_failures": field_failures,
        }

    def dump_jsonl(self, path: str | Path) -> None:
        """Append every per-entry record (one JSON object per line)."""

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(asdict(r)) + "\n")

    def dump_summary(self, path: str | Path) -> None:
        """Append one summary record for this run."""

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(), **self.summary}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def render(self) -> str:
        """Human-readable end-of-run table for the CLI."""

        s = self.summary
        if not s["total"]:
            return "cv parse: no entries"
        lines = [
            f"cv parse: {s['total']} entries — "
            f"{s['deterministic']} deterministic ({s['det_rate']:.0%}), "
            f"{s['llm']} via LLM fallback, {s['failed']} failed",
        ]
        for section, counts in sorted(s["by_section"].items()):
            tot = sum(counts.values())
            lines.append(
                f"  {section:<14} {tot:>4}  det {counts['deterministic']:>4}"
                f"  llm {counts['llm']:>4}  failed {counts['failed']:>4}"
            )
        if s["field_failures"]:
            worst = sorted(s["field_failures"].items(), key=lambda kv: -kv[1])
            lines.append(
                "  field failures: "
                + ", ".join(f"{k}={v}" for k, v in worst)
            )
        return "\n".join(lines)


def load_records(path: str | Path) -> list[dict]:
    """Read a metrics JSONL log back into dict rows (empty if absent)."""

    p = Path(path)
    if not p.exists():
        return []
    return [
        json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
