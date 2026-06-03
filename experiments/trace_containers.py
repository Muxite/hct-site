"""Trace speed / CPU / memory across the backend containers (ujin + hct-manager).

    python experiments/trace_containers.py --duration 60 --interval 1

Samples ``docker stats`` for the compose services on an interval while you run
the agent in another terminal (``docker compose run --rm hct-manager run``), then
writes a CSV and matplotlib plots (CPU% and memory over time, per container) into
``experiments/runs/trace-<timestamp>/``.

The parsing helpers are pure and unit-tested; the sampling shells out to docker.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_UNITS_MIB = {"B": 1 / (1024 * 1024), "KIB": 1 / 1024, "MIB": 1.0, "GIB": 1024.0, "KB": 1 / 1024,
              "MB": 1.0, "GB": 1024.0}


def parse_mem_to_mib(value: str) -> float:
    """'12.5MiB' / '1.9GiB' -> MiB as float. Returns 0.0 on junk."""

    value = value.strip()
    for unit, factor in sorted(_UNITS_MIB.items(), key=lambda kv: -len(kv[0])):
        if value.upper().endswith(unit):
            try:
                return float(value[: -len(unit)].strip()) * factor
            except ValueError:
                return 0.0
    return 0.0


def parse_cpu_perc(value: str) -> float:
    """'12.34%' -> 12.34. Returns 0.0 on junk."""

    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return 0.0


@dataclass
class Sample:
    t: float          # seconds since trace start
    name: str
    cpu_perc: float
    mem_mib: float
    mem_perc: float


def sample_once(services: list[str]) -> list[dict]:
    """One `docker stats --no-stream` snapshot, as a list of raw dicts (one per container)."""

    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *services],
        capture_output=True, text=True, check=True,
    )
    rows = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def trace(services: list[str], *, duration: float, interval: float) -> list[Sample]:
    """Sample docker stats every ``interval`` seconds for ``duration`` seconds."""

    samples: list[Sample] = []
    start = time.monotonic()
    while time.monotonic() - start < duration:
        t = time.monotonic() - start
        try:
            rows = sample_once(services)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"docker stats failed: {exc}", file=sys.stderr)
            break
        for r in rows:
            samples.append(Sample(
                t=round(t, 2),
                name=r.get("Name", "?"),
                cpu_perc=parse_cpu_perc(r.get("CPUPerc", "0%")),
                mem_mib=parse_mem_to_mib(r.get("MemUsage", "0B").split("/")[0]),
                mem_perc=parse_cpu_perc(r.get("MemPerc", "0%")),
            ))
        time.sleep(interval)
    return samples


def write_csv(samples: list[Sample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "container", "cpu_perc", "mem_mib", "mem_perc"])
        for s in samples:
            w.writerow([s.t, s.name, s.cpu_perc, s.mem_mib, s.mem_perc])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--services", nargs="+", default=["ujin", "hct-manager"])
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    print(f"Tracing {args.services} for {args.duration}s every {args.interval}s ...")
    samples = trace(args.services, duration=args.duration, interval=args.interval)
    if not samples:
        print("No samples collected (are the containers running? is docker installed?).")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else _REPO_ROOT / "experiments" / "runs" / f"trace-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(samples, out_dir / "trace.csv")

    sys.path.insert(0, str(_REPO_ROOT))
    from experiments import plot

    plot.plot_container_trace(samples, "cpu_perc", "CPU (%)", out_dir / "cpu.png")
    plot.plot_container_trace(samples, "mem_mib", "Memory (MiB)", out_dir / "mem.png")
    peak = {}
    for s in samples:
        peak[s.name] = max(peak.get(s.name, 0.0), s.mem_mib)
    print("peak memory:", ", ".join(f"{k}={v:.0f}MiB" for k, v in peak.items()))
    print(f"Wrote trace + plots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
