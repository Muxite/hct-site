"""matplotlib plots for the agent experiment + token metrics.

Imported only by the runnable harness, which opts into the matplotlib
dependency (``pip install -e 'backend[experiments]'``). Uses the non-interactive
Agg backend so it renders to PNG without a display.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def plot_rates(report, out: str | Path) -> Path:
    """Bar chart of the three quality rates (parse error / hard fail / hallucination)."""

    labels = ["parse-error", "hard-failure", "hallucination"]
    values = [report.parse_error_rate, report.hard_failure_rate, report.hallucination_rate]
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, [v * 100 for v in values], color=["#f0ad4e", "#d9534f", "#5bc0de"])
    ax.set_ylabel("rate (%)")
    ax.set_ylim(0, max(5, max(values) * 100 * 1.3 or 5))
    ax.set_title(f"Agent quality rates ({report.model}, n={report.n}, T={report.temperature})")
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:.1%}", ha="center", va="bottom")
    fig.tight_layout()
    return _save(fig, out)


def plot_tokens_per_trial(report, out: str | Path) -> Path:
    """Stacked prompt/completion tokens per trial, with a latency line on a twin axis."""

    trials = list(range(1, report.n + 1))
    prompt = [t.prompt_tokens for t in report.trials]
    completion = [t.completion_tokens for t in report.trials]
    latency = [t.latency_s for t in report.trials]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(trials, prompt, label="prompt", color="#4c72b0")
    ax.bar(trials, completion, bottom=prompt, label="completion", color="#dd8452")
    ax.set_xlabel("trial")
    ax.set_ylabel("tokens")
    ax.set_title(f"Token usage per trial ({report.model})")
    ax.legend(loc="upper left")

    ax2 = ax.twinx()
    ax2.plot(trials, latency, "o-", color="#55a868", label="latency")
    ax2.set_ylabel("latency (s)")
    ax2.legend(loc="upper right")
    fig.tight_layout()
    return _save(fig, out)


def plot_usage_by_stage(records: list[dict], out: str | Path) -> Path:
    """Stacked prompt/completion tokens grouped by call label, from metrics.jsonl rows."""

    prompt: dict[str, int] = defaultdict(int)
    completion: dict[str, int] = defaultdict(int)
    for r in records:
        label = r.get("label") or "?"
        prompt[label] += int(r.get("prompt_tokens", 0))
        completion[label] += int(r.get("completion_tokens", 0))
    stages = sorted(prompt.keys() | completion.keys())

    fig, ax = plt.subplots(figsize=(7, 4))
    p = [prompt[s] for s in stages]
    c = [completion[s] for s in stages]
    ax.bar(stages, p, label="prompt", color="#4c72b0")
    ax.bar(stages, c, bottom=p, label="completion", color="#dd8452")
    ax.set_ylabel("tokens")
    ax.set_title("Token usage by stage (all recorded runs)")
    ax.legend()
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    return _save(fig, out)


def plot_container_trace(samples, attr: str, ylabel: str, out: str | Path) -> Path:
    """Line per container of ``attr`` (e.g. cpu_perc / mem_mib) over time."""

    by_name: dict[str, list] = defaultdict(list)
    for s in samples:
        by_name[s.name].append((s.t, getattr(s, attr)))
    fig, ax = plt.subplots(figsize=(7, 4))
    for name, series in sorted(by_name.items()):
        series.sort()
        ax.plot([t for t, _ in series], [v for _, v in series], "o-", label=name, markersize=3)
    ax.set_xlabel("time (s)")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} per container")
    ax.legend()
    fig.tight_layout()
    return _save(fig, out)


def _save(fig, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
