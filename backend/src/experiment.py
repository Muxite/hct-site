"""Agent performance evaluation: error rate, hallucination rate, token cost.

The goal for this branch is the *lightest* agent that can extract a lab's
publications. This module measures whether it actually does the job well, on the
one input we can reach offline (the static ``#publications-static`` block — Google
Scholar bot-blocks the runner IP). It runs extraction over several trials and
reports:

* **parse-error rate** — trials whose first LLM output failed JSON parse/validation
  (needed the repair round-trip).
* **hard-failure rate** — trials that failed even after the one repair retry.
* **hallucination rate** — extracted papers whose title is not grounded in the
  source text (the model invented or mis-merged an entry), over all papers.
* **token usage / latency / est. cost** — from the LLM call records.

Everything here is pure logic with the LLM injected, so it is unit-tested with a
fake model and no network. The runnable harness (real model + matplotlib plots)
lives in ``experiments/run.py``.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from src.extract import build_user_prompt, parse_publication_set
from src.metrics import UsageTracker, estimate_cost


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def count_hallucinations(titles: list[str], source_norm: str) -> tuple[int, list[str]]:
    """Return (#ungrounded, the ungrounded titles): titles absent from the source."""

    missing = [t for t in titles if normalize(t) and normalize(t) not in source_norm]
    return len(missing), missing


@dataclass
class TrialResult:
    first_pass_ok: bool
    final_ok: bool
    n_pubs: int
    n_hallucinated: int
    hallucinated_titles: list[str]
    prompt_tokens: int
    completion_tokens: int
    latency_s: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def evaluate_once(
    source_text: str,
    *,
    llm,
    system_prompt: str,
    source_norm: str,
    temperature: float = 0.0,
    max_page_chars: int = 6000,
) -> TrialResult:
    """Run one extraction trial (with the same first-pass + repair logic) and measure it.

    ``llm`` must accept a ``label`` kwarg and (for token capture) carry a
    :class:`UsageTracker` on ``.tracker``; a fresh tracker is installed so this
    trial's tokens are isolated.
    """

    tracker = UsageTracker(label="experiment")
    if hasattr(llm, "tracker"):
        llm.tracker = tracker

    user = build_user_prompt(source_text, max_page_chars=max_page_chars)
    raw = llm.complete(system=system_prompt, user=user, temperature=temperature, label="extract")

    first_pass_ok = True
    ps = None
    try:
        ps = parse_publication_set(raw)
    except Exception:  # noqa: BLE001 — any parse/validation failure triggers repair
        first_pass_ok = False
        repair_user = (
            "Your previous answer could not be used:\n"
            f"{raw.strip()}\n\nReturn corrected JSON only, matching the schema."
        )
        raw2 = llm.complete(
            system=system_prompt, user=repair_user, temperature=temperature, label="extract-repair"
        )
        try:
            ps = parse_publication_set(raw2)
        except Exception:  # noqa: BLE001
            ps = None

    final_ok = ps is not None
    titles = [p.title for p in ps.publications] if ps else []
    n_halluc, halluc_titles = count_hallucinations(titles, source_norm)
    totals = tracker.totals
    return TrialResult(
        first_pass_ok=first_pass_ok,
        final_ok=final_ok,
        n_pubs=len(titles),
        n_hallucinated=n_halluc,
        hallucinated_titles=halluc_titles,
        prompt_tokens=totals["prompt_tokens"],
        completion_tokens=totals["completion_tokens"],
        latency_s=totals["latency_s"],
    )


@dataclass
class ExperimentReport:
    model: str
    trials: list[TrialResult] = field(default_factory=list)
    temperature: float = 0.0

    @property
    def n(self) -> int:
        return len(self.trials)

    @property
    def parse_error_rate(self) -> float:
        return self._rate(lambda t: not t.first_pass_ok)

    @property
    def hard_failure_rate(self) -> float:
        return self._rate(lambda t: not t.final_ok)

    @property
    def hallucination_rate(self) -> float:
        total = sum(t.n_pubs for t in self.trials)
        halluc = sum(t.n_hallucinated for t in self.trials)
        return (halluc / total) if total else 0.0

    def _rate(self, pred) -> float:
        return (sum(1 for t in self.trials if pred(t)) / self.n) if self.n else 0.0

    @property
    def avg_total_tokens(self) -> float:
        return statistics.mean([t.total_tokens for t in self.trials]) if self.trials else 0.0

    @property
    def avg_latency_s(self) -> float:
        return statistics.mean([t.latency_s for t in self.trials]) if self.trials else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(
            estimate_cost(self.model, t.prompt_tokens, t.completion_tokens) for t in self.trials
        )

    def render(self) -> str:
        avg_pubs = statistics.mean([t.n_pubs for t in self.trials]) if self.trials else 0
        lines = [
            "AGENT PERFORMANCE EXPERIMENT",
            f"model: {self.model}   trials: {self.n}   temperature: {self.temperature}",
            "=" * 60,
            f"  parse-error rate     {self.parse_error_rate:6.1%}   (needed repair retry)",
            f"  hard-failure rate    {self.hard_failure_rate:6.1%}   (invalid after repair)",
            f"  hallucination rate   {self.hallucination_rate:6.1%}   (ungrounded papers / total)",
            "  " + "-" * 56,
            f"  avg papers/run       {avg_pubs:6.1f}",
            f"  avg tokens/run       {self.avg_total_tokens:6.0f}",
            f"  avg latency/run      {self.avg_latency_s:6.2f}s",
            f"  est. total cost      ${self.total_cost_usd:.4f}",
        ]
        halluc = sorted({t for tr in self.trials for t in tr.hallucinated_titles})
        if halluc:
            lines.append("  " + "-" * 56)
            lines.append("  ungrounded titles seen:")
            lines.extend(f"    - {h}" for h in halluc[:20])
        return "\n".join(lines) + "\n"


def run_trials(
    source_text: str,
    *,
    llm,
    system_prompt: str,
    model: str,
    trials: int = 5,
    temperature: float = 0.0,
    max_page_chars: int = 6000,
) -> ExperimentReport:
    """Run ``trials`` extraction trials over ``source_text`` and aggregate metrics."""

    source_norm = normalize(source_text)
    report = ExperimentReport(model=model, temperature=temperature)
    for _ in range(trials):
        report.trials.append(
            evaluate_once(
                source_text,
                llm=llm,
                system_prompt=system_prompt,
                source_norm=source_norm,
                temperature=temperature,
                max_page_chars=max_page_chars,
            )
        )
    return report
