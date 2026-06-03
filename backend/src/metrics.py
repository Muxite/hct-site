"""Lightweight token + latency metrics for LLM calls.

Every OpenRouter response carries a ``usage`` block; :class:`OpenRouterClient`
records one :class:`CallRecord` per call onto an optional :class:`UsageTracker`.
The tracker summarizes totals/cost and can append to a JSONL log
(``state/metrics.jsonl``) that the experimentation + plotting tools read back.

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


def load_records(path: str | Path) -> list[dict]:
    """Read a metrics JSONL log back into dict rows (empty if absent)."""

    p = Path(path)
    if not p.exists():
        return []
    return [
        json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
