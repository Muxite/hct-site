"""Unit tests for the agent performance experiment (fake LLM, no network)."""

from __future__ import annotations

from src import experiment

_VALID = '{"publications":[{"title":"Real Paper","authors":["Ann Lee"],"year":2022,"type":"article"}]}'
_VALID_HALLUC = '{"publications":[{"title":"Invented Work","authors":["Ann Lee"],"year":2022,"type":"article"}]}'
_SOURCE = "Real Paper, Ann Lee, 2022. Another Real Paper, 2021."
_SOURCE_NORM = experiment.normalize(_SOURCE)


class FakeLLM:
    """Returns scripted responses by call index (clamped); records token usage."""

    def __init__(self, scripted, model="fake"):
        self.tracker = None
        self.model = model
        self.scripted = list(scripted)
        self.calls = 0

    def complete(self, *, system, user, temperature=0.0, label="", **kw):
        resp = self.scripted[min(self.calls, len(self.scripted) - 1)]
        self.calls += 1
        if self.tracker is not None:
            self.tracker.record(
                model=self.model,
                usage={"prompt_tokens": 100, "completion_tokens": 20},
                latency_s=0.1, label=label,
            )
        return resp


def test_count_hallucinations():
    n, missing = experiment.count_hallucinations(["Real Paper", "Invented Work"], _SOURCE_NORM)
    assert n == 1 and missing == ["Invented Work"]


def test_evaluate_once_clean():
    llm = FakeLLM([_VALID])
    r = experiment.evaluate_once(_SOURCE, llm=llm, system_prompt="s", source_norm=_SOURCE_NORM)
    assert r.first_pass_ok and r.final_ok
    assert r.n_pubs == 1 and r.n_hallucinated == 0
    assert r.total_tokens == 120 and r.latency_s > 0


def test_evaluate_once_repair():
    llm = FakeLLM(["this is not json", _VALID])
    r = experiment.evaluate_once(_SOURCE, llm=llm, system_prompt="s", source_norm=_SOURCE_NORM)
    assert r.first_pass_ok is False and r.final_ok is True
    assert llm.calls == 2  # first + repair


def test_evaluate_once_hard_failure():
    llm = FakeLLM(["nope", "still nope"])
    r = experiment.evaluate_once(_SOURCE, llm=llm, system_prompt="s", source_norm=_SOURCE_NORM)
    assert r.first_pass_ok is False and r.final_ok is False
    assert r.n_pubs == 0


def test_evaluate_once_hallucination():
    llm = FakeLLM([_VALID_HALLUC])
    r = experiment.evaluate_once(_SOURCE, llm=llm, system_prompt="s", source_norm=_SOURCE_NORM)
    assert r.n_pubs == 1 and r.n_hallucinated == 1
    assert r.hallucinated_titles == ["Invented Work"]


def test_run_trials_aggregates_rates():
    llm = FakeLLM([_VALID])
    report = experiment.run_trials(_SOURCE, llm=llm, system_prompt="s", model="fake", trials=4)
    assert report.n == 4
    assert report.parse_error_rate == 0.0
    assert report.hard_failure_rate == 0.0
    assert report.hallucination_rate == 0.0
    assert report.avg_total_tokens == 120
    assert report.total_cost_usd == 0.0  # unknown model -> zero pricing
    text = report.render()
    assert "AGENT PERFORMANCE EXPERIMENT" in text
    assert "hallucination rate" in text


def test_run_trials_mixed_hallucination_rate():
    # 2 trials: one clean (1 grounded), one hallucinated (1 ungrounded) -> 50%.
    llm = FakeLLM([_VALID, _VALID_HALLUC])
    report = experiment.run_trials(_SOURCE, llm=llm, system_prompt="s", model="fake", trials=2)
    assert report.hallucination_rate == 0.5
