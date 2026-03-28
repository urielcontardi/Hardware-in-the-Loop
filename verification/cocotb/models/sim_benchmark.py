"""Simulation benchmark logger.

Appends a structured entry to reports/sim_benchmark.json at the end of every
VHDL cocotb test so that wall-clock performance can be tracked across runs,
simulators, and machines.

Usage
-----
    from models.sim_benchmark import save_benchmark
    import time

    t0 = time.monotonic()
    # ... run simulation ...
    save_benchmark(
        test_name  = "tim_solver_vf",
        sim_steps  = SIM_STEPS,
        ts_s       = 100e-9,
        wall_time_s= time.monotonic() - t0,
        extra      = {"nrmse_i_alpha": 0.0003, "mae_speed_rad_s": 0.12},
    )
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any


REPORTS_DIR    = Path(__file__).resolve().parents[1] / "reports"
BENCHMARK_PATH = REPORTS_DIR / "sim_benchmark.json"


def _detect_simulator() -> str:
    """Return a version string for the active simulator (nvc / ghdl / unknown)."""
    for cmd in (["nvc", "--version"], ["ghdl", "--version"]):
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            return out.splitlines()[0].strip()
        except Exception:
            continue
    return os.environ.get("SIM", "unknown")


def save_benchmark(
    test_name: str,
    sim_steps: int,
    ts_s: float,
    wall_time_s: float,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one benchmark entry to sim_benchmark.json.

    Parameters
    ----------
    test_name   : short identifier, e.g. "tim_solver_vf"
    sim_steps   : total motor steps simulated
    ts_s        : discretisation step in seconds
    wall_time_s : elapsed wall-clock time for the simulation loop
    extra       : optional dict of additional key/value pairs (metrics, flags…)
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        existing: list = (
            json.loads(BENCHMARK_PATH.read_text()) if BENCHMARK_PATH.exists() else []
        )
    except (json.JSONDecodeError, OSError):
        existing = []

    motor_time_s  = sim_steps * ts_s
    msteps_per_s  = sim_steps / wall_time_s if wall_time_s > 0 else 0.0

    entry: dict[str, Any] = {
        "date":           time.strftime("%Y-%m-%dT%H:%M:%S"),
        "test_name":      test_name,
        "sim_duration_s": round(motor_time_s, 6),
        "sim_steps":      sim_steps,
        "ts_ns":          round(ts_s * 1e9, 3),
        "simulator":      _detect_simulator(),
        "host":           platform.node(),
        "cpu_count":      os.cpu_count(),
        "wall_time_s":    round(wall_time_s, 2),
        "msteps_per_s":   round(msteps_per_s, 3),
    }
    if extra:
        entry.update(extra)

    existing.append(entry)
    BENCHMARK_PATH.write_text(json.dumps(existing, indent=2))
    print(
        f"[benchmark] {test_name}  "
        f"{motor_time_s:.3f}s motor / {wall_time_s:.1f}s wall  "
        f"({msteps_per_s:.3f} Msteps/s)  → {BENCHMARK_PATH.name}",
        flush=True,
    )
