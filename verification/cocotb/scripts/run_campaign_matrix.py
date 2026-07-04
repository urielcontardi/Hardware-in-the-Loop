#!/usr/bin/env python3
"""Orquestrador da campaign_03 — roda a matriz S0+Grupo A (22 experimentos)
em paralelo, isolando a work library do simulador por experimento e o .so do
modelo C via priming serial (ver prime_c_model.py).

Uso:
    cd verification/cocotb
    uv run python scripts/run_campaign_matrix.py \\
        --config campaigns/campaign_03_full_matrix.json --max-parallel 4

    # Rodar so um caso:
    uv run python scripts/run_campaign_matrix.py --config ... --only A1_l2

    # So imprimir o plano, sem rodar nada:
    uv run python scripts/run_campaign_matrix.py --config ... --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_campaign import (  # noqa: E402
    build_l3_env, cocotb_root, env_number, generate_l3_overlay,
    load_json, project_root, run_cocotb, write_readme,
)
from prime_c_model import ensure_c_model_built  # noqa: E402

SUMMARY_FIELDS = [
    "case", "level", "status", "path", "duration_s", "t_acc_s", "tload_nm",
    "csv_rows", "nrmse_i_alpha", "nrmse_i_beta", "mae_flux_alpha_wb",
    "mae_flux_beta_wb", "mae_speed_rad_s", "overlay", "note",
]


# ── Env builders ──────────────────────────────────────────────────────────────

def build_l2_env(config: dict[str, Any], exp: dict[str, Any], out_dir: Path) -> dict[str, str]:
    """Build the environment for a tim_solver L2 run (test_mode 'vf' or 'sine')."""
    import os

    defaults = config.get("defaults", {})
    motor = defaults.get("motor", {})
    clock = int(defaults.get("im_clock_frequency", 200_000_000))
    step_cycles = int(defaults.get("im_solver_step_cycles", 26))
    ts = step_cycles / clock

    env = os.environ.copy()
    env.update({
        "IM_CLOCK_FREQUENCY": env_number(clock),
        "IM_SOLVER_STEP_CYCLES": env_number(step_cycles),
        "IM_RS": env_number(motor.get("rs", 0.4396)),
        "IM_RR": env_number(motor.get("rr", 0.2826)),
        "IM_LS": env_number(motor.get("ls", 0.0031364)),
        "IM_LR": env_number(motor.get("lr", 0.0063264)),
        "IM_LM": env_number(motor.get("lm", 0.1099442)),
        "IM_J": env_number(motor.get("j", 0.4)),
        "IM_NPP": env_number(motor.get("npp", 2.0)),
    })

    test_mode = exp["test_mode"]
    theta = exp.get("initial_theta_rad", defaults.get("initial_theta_rad", 0.7853981633974483))
    v_peak = exp.get("v_peak", defaults.get("v_peak", 620.0))
    warmup = exp.get("warmup_steps", defaults.get("warmup_steps", 400))

    if test_mode == "vf":
        env.update({
            "HIL_VF_DURATION_S": env_number(exp["duration_s"]),
            "HIL_VF_RECORD_INTERVAL": env_number(exp["record_interval"]),
            "HIL_VF_WARMUP_STEPS": env_number(warmup),
            "HIL_VF_F_NOMINAL_HZ": env_number(exp.get("vf_base_hz", 60.0)),
            "HIL_VF_V_PEAK_NOMINAL": env_number(v_peak),
            "HIL_VF_ACC_RAMP_HZ_S": env_number(exp["vf_acc_hz_s"]),
            "HIL_VF_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_VF_INITIAL_THETA_RAD": env_number(theta),
            "HIL_VF_CSV": str((out_dir / "vf_vhdl_vs_c.csv").resolve()),
            "HIL_VF_METRICS": str((out_dir / "metrics.json").resolve()),
        })
    elif test_mode == "sine":
        steps = int(exp["steps"]) if "steps" in exp else round(float(exp["duration_s"]) / ts)
        env.update({
            "HIL_SINE_STEPS": env_number(steps),
            "HIL_SINE_WARMUP_STEPS": env_number(exp.get("warmup_steps", 50)),
            "HIL_SINE_FREQ_HZ": env_number(exp.get("sine_freq_hz", 60.0)),
            "HIL_SINE_V_PEAK": env_number(v_peak),
            "HIL_SINE_INITIAL_THETA_RAD": env_number(theta),
            "HIL_SINE_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_SINE_CSV": str((out_dir / "sine_vhdl_vs_c.csv").resolve()),
            "HIL_SINE_METRICS": str((out_dir / "metrics.json").resolve()),
        })
    else:
        raise ValueError(f"unknown L2 test_mode: {test_mode!r}")
    return env


# ── manifest / summary bookkeeping (single-threaded — only main() calls these) ──

def load_manifest(path: Path) -> dict[str, Any]:
    return load_json(path)


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2))


def update_manifest_case(
    manifest: dict[str, Any], case_id: str, level: str, result_key: str,
    output_dir: str, ok: bool,
) -> None:
    case = next(c for c in manifest["cases"] if c["id"] == case_id)
    if not ok:
        case["status"] = "blocked"
        return
    results_key = "l2_results" if level == "l2" else "l3_results"
    case[results_key][result_key] = output_dir
    has_l2 = bool(case.get("l2_results"))
    has_l3 = bool(case.get("l3_results"))
    if has_l2 and has_l3:
        case["status"] = "l2_l3_generated"
    elif has_l2 or has_l3:
        case["status"] = "partial_generated"


def append_summary_row(csv_path: Path, row: dict[str, Any]) -> None:
    is_new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in SUMMARY_FIELDS})
