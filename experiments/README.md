# experiments — agent performance

Measures how well the (lightest-possible) extraction agent does its job, and how
much it costs. The core metric logic lives in `backend/src/experiment.py` (unit
tested with a fake model); this directory is the runnable harness + matplotlib
plots.

## What it measures

Over N trials of extracting the lab's publications from the static page block
(Google Scholar bot-blocks the runner IP, so the static page is our offline
ground truth):

- **parse-error rate** — first LLM output failed JSON parse/validation (needed the repair retry).
- **hard-failure rate** — still invalid after the one repair retry.
- **hallucination rate** — extracted papers whose title is not grounded in the source text, over all papers.
- **token usage / latency / est. cost** — from the recorded LLM call metrics.

Trials run at a non-zero temperature by default (`--temperature 0.4`) so the
rates reflect real variability rather than one deterministic sample.

## Run

```bash
pip install -e 'backend[experiments]'     # adds matplotlib
# OPENROUTER_API_KEY must be set (e.g. `set -a && . .env && set +a`)
python experiments/run.py --trials 5
```

Outputs to `experiments/runs/<timestamp>/`:
- `report.txt` — the rates + token/cost summary
- `rates.png` — parse-error / hard-failure / hallucination bar chart
- `tokens.png` — prompt+completion tokens and latency per trial
- `usage_by_stage.png` — token usage grouped by call stage, from
  `backend/data/state/metrics.jsonl` (covers real `run`/`describe`/`import-html` runs)

## Notes

- The model is whatever the agent uses (`OPENROUTER_MODEL`, default
  `google/gemini-3-flash-preview`). Change it to compare models on the same task.
- `runs/` is gitignored.
