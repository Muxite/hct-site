"""Run the agent performance experiment against the live model + write plots.

    python experiments/run.py [--trials N] [--temperature T] [--max-chars N]

Extracts the lab's publications from the static page block over several trials
(Google Scholar bot-blocks the runner IP, so the static page is our offline
ground truth), measures error/hallucination rates + token cost, and writes a
report and matplotlib PNGs into ``experiments/runs/<timestamp>/``. Also plots
token usage by stage from ``backend/data/state/metrics.jsonl`` if present (so the
real run/describe/import-html runs show up too).

Needs OPENROUTER_API_KEY in the environment (or .env), and the experiments deps:
    pip install -e 'backend[experiments]'
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT))  # so `from experiments import plot` resolves

from src import content, experiment  # noqa: E402
from src.config import Config  # noqa: E402
from src.extract import load_system_prompt  # noqa: E402
from src.llm import OpenRouterClient  # noqa: E402
from src.metrics import UsageTracker, load_records  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=0.4,
                    help="higher surfaces variability so rates are meaningful (default 0.4)")
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--out", default=None, help="output dir (default experiments/runs/<ts>)")
    args = ap.parse_args(argv)

    cfg = Config.from_env()
    source = content.publications_block_text(cfg.index_html.read_text(encoding="utf-8"))
    if not source:
        print(f"No #publications-static block in {cfg.index_html}.")
        return 1
    system_prompt = load_system_prompt(cfg.templates_dir)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else _REPO_ROOT / "experiments" / "runs" / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {args.trials} trials @ T={args.temperature} on {cfg.model} ...")
    with OpenRouterClient(cfg.openrouter_api_key, model=cfg.model,
                          base_url=cfg.openrouter_base_url, tracker=UsageTracker()) as llm:
        report = experiment.run_trials(
            source, llm=llm, system_prompt=system_prompt, model=cfg.model,
            trials=args.trials, temperature=args.temperature, max_page_chars=args.max_chars,
        )

    text = report.render()
    print("\n" + text)
    (out_dir / "report.txt").write_text(text, encoding="utf-8")

    from experiments import plot  # lazy: only now do we need matplotlib

    plot.plot_rates(report, out_dir / "rates.png")
    plot.plot_tokens_per_trial(report, out_dir / "tokens.png")
    records = load_records(cfg.state_dir / "metrics.jsonl")
    if records:
        plot.plot_usage_by_stage(records, out_dir / "usage_by_stage.png")
    print(f"Wrote report + plots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
