"""Generate N lab-voice descriptions on the live model and report their quality.

This is the *generative* counterpart to ``run.py`` (which stresses extraction).
Descriptions are the content the lab actually publishes, so this harness gathers
a batch of them, applies cheap automated quality checks (grounding, length,
stylistic tics), and writes a reviewable item-by-item report.

    python experiments/describe_eval.py [--n 30] [--temperature T] [--repeat-trials K]

Source is offline: publications are extracted once from the static
``#publications-static`` block (Scholar bot-blocks the runner), then each paper
is described from its metadata (no per-paper fetch, so grounding == metadata).

Needs OPENROUTER_API_KEY (read from env or the repo ``.env``).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from src import content  # noqa: E402
from src.config import Config  # noqa: E402
from src.describe import describe_publication, load_describe_system_prompt  # noqa: E402
from src.extract import extract_publications, load_system_prompt  # noqa: E402
from src.llm import OpenRouterClient  # noqa: E402
from src.metrics import UsageTracker, cost_breakdown  # noqa: E402
from src.models import Publication  # noqa: E402


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines into os.environ (no overwrite)."""
    import os

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_FILLER_OPENERS = (
    "this paper", "in this paper", "this study", "this work", "the paper",
    "this research", "this article", "in this work", "we ",
)
_SENT_SPLIT = re.compile(r"[.!?]+(?:\s|$)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _numbers(s: str) -> set[str]:
    # Standalone numeric tokens (ignore things like "3D" / "COVID-19" partially).
    return set(re.findall(r"(?<![\w-])\d+(?:\.\d+)?(?![\w])", s or ""))


@dataclass
class ItemResult:
    idx: int
    title: str
    description: str
    ok: bool                       # non-empty output, call succeeded
    n_words: int
    n_sentences: int
    too_long: bool                 # > 3 sentences or > 90 words (intent: 2-3 sentences)
    too_short: bool                # < 8 words
    repeats_title: bool            # echoes the title back (prompt forbids this)
    filler_opening: bool           # "This paper...", "We ...", etc.
    ungrounded_numbers: list[str]  # numeric tokens not in the metadata
    prompt_tokens: int
    completion_tokens: int
    latency_s: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def clean(self) -> bool:
        return (
            self.ok
            and not self.too_long
            and not self.too_short
            and not self.repeats_title
            and not self.filler_opening
            and not self.ungrounded_numbers
        )


def evaluate_description(idx: int, pub: Publication, desc: str, *, tracker: UsageTracker) -> ItemResult:
    desc = (desc or "").strip()
    meta = _norm(" ".join([pub.title, "; ".join(pub.authors), str(pub.year), pub.venue or ""]))
    meta_numbers = _numbers(meta) | {str(pub.year)}
    words = re.findall(r"\b\w+\b", desc)
    sentences = [s for s in _SENT_SPLIT.split(desc) if s.strip()]
    n_words, n_sent = len(words), len(sentences)
    ndesc = _norm(desc)
    ntitle = _norm(pub.title)

    ungrounded = sorted(_numbers(desc) - meta_numbers)
    totals = tracker.totals
    return ItemResult(
        idx=idx,
        title=pub.title,
        description=desc,
        ok=bool(desc),
        n_words=n_words,
        n_sentences=n_sent,
        too_long=(n_sent > 3 or n_words > 90),
        too_short=(n_words < 8),
        repeats_title=(len(ntitle) > 12 and ntitle in ndesc),
        filler_opening=ndesc.startswith(_FILLER_OPENERS),
        ungrounded_numbers=ungrounded,
        prompt_tokens=totals["prompt_tokens"],
        completion_tokens=totals["completion_tokens"],
        latency_s=totals["latency_s"],
    )


@dataclass
class DescribeReport:
    model: str
    temperature: float
    style_profile_used: bool
    items: list[ItemResult] = field(default_factory=list)

    def _rate(self, pred) -> float:
        return (sum(1 for it in self.items if pred(it)) / len(self.items)) if self.items else 0.0

    def render(self) -> str:
        n = len(self.items)
        in_tokens = sum(it.prompt_tokens for it in self.items)
        out_tokens = sum(it.completion_tokens for it in self.items)
        cost = cost_breakdown(self.model, in_tokens, out_tokens)
        avg_words = statistics.mean([it.n_words for it in self.items]) if self.items else 0
        avg_sent = statistics.mean([it.n_sentences for it in self.items]) if self.items else 0
        L = [
            "DESCRIBE-STAGE QUALITY REPORT",
            f"model: {self.model}   items: {n}   temperature: {self.temperature}"
            f"   style_profile: {'yes' if self.style_profile_used else 'no'}",
            "=" * 64,
            f"  call-failure rate     {self._rate(lambda i: not i.ok):6.1%}",
            f"  too-long rate         {self._rate(lambda i: i.too_long):6.1%}   (>3 sentences / >90 words)",
            f"  too-short rate        {self._rate(lambda i: i.too_short):6.1%}   (<8 words)",
            f"  repeats-title rate    {self._rate(lambda i: i.repeats_title):6.1%}",
            f"  filler-opening rate   {self._rate(lambda i: i.filler_opening):6.1%}   ('This paper...', 'We ...')",
            f"  ungrounded-number rate{self._rate(lambda i: bool(i.ungrounded_numbers)):6.1%}",
            f"  CLEAN rate            {self._rate(lambda i: i.clean):6.1%}   (no flags at all)",
            "  " + "-" * 60,
            f"  avg words/desc        {avg_words:6.1f}",
            f"  avg sentences/desc    {avg_sent:6.1f}",
            f"  avg tokens/desc       {statistics.mean([it.total_tokens for it in self.items]):6.0f}"
            if self.items else "  avg tokens/desc        n/a",
            f"  avg latency/desc      {statistics.mean([it.latency_s for it in self.items]):6.2f}s"
            if self.items else "  avg latency/desc       n/a",
            "  " + "-" * 60,
            f"  total input tokens    {in_tokens:8d}   (${cost['input_cost_usd']:.4f})",
            f"  total output tokens   {out_tokens:8d}   (${cost['output_cost_usd']:.4f})",
            f"  est. total cost       ${cost['total_cost_usd']:.4f}",
            "=" * 64,
            "ITEMS (flags: L=long S=short T=title-echo F=filler N=ungrounded#):",
        ]
        for it in self.items:
            flags = "".join([
                "L" if it.too_long else "",
                "S" if it.too_short else "",
                "T" if it.repeats_title else "",
                "F" if it.filler_opening else "",
                "N" if it.ungrounded_numbers else "",
            ]) or "ok"
            L.append(f"\n[{it.idx:02d}] <{flags}> {it.n_words}w/{it.n_sentences}s  {it.title[:70]}")
            L.append(f"      {it.description}")
            if it.ungrounded_numbers:
                L.append(f"      ungrounded #: {', '.join(it.ungrounded_numbers)}")
        return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=30, help="number of descriptions to generate")
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument("--no-style", action="store_true", help="skip the saved style profile")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    _load_dotenv(_REPO_ROOT / ".env")
    cfg = Config.from_env()

    source = content.publications_block_text(cfg.index_html.read_text(encoding="utf-8"))
    if not source:
        print(f"No #publications-static block in {cfg.index_html}.")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else _REPO_ROOT / "experiments" / "runs" / f"describe-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Style profile (the tone the descriptions should match), if one was saved.
    style_path = cfg.state_dir / "style_profile.txt"
    style_profile = style_path.read_text(encoding="utf-8").strip() if style_path.exists() else ""
    if args.no_style:
        style_profile = ""

    describe_system = load_describe_system_prompt(cfg.templates_dir)

    with OpenRouterClient(cfg.openrouter_api_key, model=cfg.model,
                          base_url=cfg.openrouter_base_url, tracker=UsageTracker()) as llm:
        print(f"Extracting publications from the static block on {cfg.model} ...")
        ps = extract_publications(
            source, llm=llm, system_prompt=load_system_prompt(cfg.templates_dir),
        )
        pubs = ps.publications[: args.n]
        print(f"Extracted {len(ps.publications)} papers; describing {len(pubs)} @ T={args.temperature} ...")

        report = DescribeReport(
            model=cfg.model, temperature=args.temperature,
            style_profile_used=bool(style_profile),
        )
        for i, pub in enumerate(pubs, 1):
            # Isolate this item's tokens so the report attributes per-description cost.
            llm.tracker = UsageTracker(label="describe")
            try:
                desc = describe_publication(
                    pub, llm=llm, system_prompt=describe_system,
                    style_profile=style_profile, source_text="",
                )
            except Exception as exc:  # noqa: BLE001 — a failed call is a measured outcome
                desc = ""
                print(f"  [{i:02d}] call failed: {exc}")
            report.items.append(evaluate_description(i, pub, desc, tracker=llm.tracker))
            print(f"  [{i:02d}] {report.items[-1].n_words}w  {pub.title[:60]}")

    text = report.render()
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    (out_dir / "items.jsonl").write_text(
        "\n".join(json.dumps(asdict(it)) for it in report.items) + "\n", encoding="utf-8"
    )
    print("\n" + text)
    print(f"Wrote report + items to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
