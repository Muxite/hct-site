"""Unit tests for the container-trace parsing helpers (no docker)."""

from __future__ import annotations

import sys
from pathlib import Path

# experiments/ is a sibling of backend/; put the repo root on the path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from experiments import trace_containers as tc  # noqa: E402


def test_parse_mem_to_mib_units():
    assert tc.parse_mem_to_mib("512MiB") == 512.0
    assert tc.parse_mem_to_mib("1.5GiB") == 1536.0
    assert round(tc.parse_mem_to_mib("1024KiB"), 3) == 1.0
    assert tc.parse_mem_to_mib("garbage") == 0.0


def test_parse_cpu_perc():
    assert tc.parse_cpu_perc("12.34%") == 12.34
    assert tc.parse_cpu_perc("0.00%") == 0.0
    assert tc.parse_cpu_perc("--") == 0.0


def test_write_csv_roundtrip(tmp_path):
    samples = [
        tc.Sample(t=0.0, name="ujin", cpu_perc=1.0, mem_mib=50.0, mem_perc=2.0),
        tc.Sample(t=1.0, name="hct-manager", cpu_perc=80.0, mem_mib=120.0, mem_perc=6.0),
    ]
    out = tmp_path / "trace.csv"
    tc.write_csv(samples, out)
    lines = out.read_text().strip().splitlines()
    assert lines[0] == "t_s,container,cpu_perc,mem_mib,mem_perc"
    assert "ujin" in lines[1] and "hct-manager" in lines[2]
