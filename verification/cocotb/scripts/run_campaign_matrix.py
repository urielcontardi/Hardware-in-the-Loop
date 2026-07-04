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


# ── Per-case execution ────────────────────────────────────────────────────────

def _is_case_already_ok(manifest: dict[str, Any], case_id: str, level: str, result_key: str) -> bool:
    case = next((c for c in manifest["cases"] if c["id"] == case_id), None)
    if case is None:
        return False
    results = case.get("l2_results" if level == "l2" else "l3_results", {})
    return result_key in results


def run_one_cocotb(config: dict[str, Any], exp: dict[str, Any], case_root: Path) -> dict[str, Any]:
    out_dir = case_root / exp["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"

    if exp["level"] == "l2":
        env = build_l2_env(config, exp, out_dir)
    else:
        env = build_l3_env(config, exp, out_dir)

    build_dir = f"sim_build/{exp['id']}"
    t0 = time.monotonic()
    with log_path.open("w") as logf:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf
        try:
            rc = run_cocotb(exp, env, build_dir=build_dir)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
    wall_s = time.monotonic() - t0

    metrics_path = out_dir / "metrics.json"
    metrics = load_json(metrics_path) if metrics_path.exists() else None
    return {"id": exp["id"], "ok": rc == 0, "wall_s": wall_s, "metrics": metrics, "out_dir": out_dir}


def run_one_fullstack_mock(config: dict[str, Any], exp: dict[str, Any], case_root: Path) -> dict[str, Any]:
    dep_id = exp["depends_on"]
    dep_exp = next(e for e in config["_experiments_by_id"].values() if e["id"] == dep_id)
    top_csv = case_root / dep_exp["output_dir"] / "top_pwm_replay_vs_c.csv"
    out_dir = case_root / exp["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"

    cmd = [
        "uv", "run", "python", "scripts/top_fullstack_mock.py", str(top_csv),
        "--out-dir", str(out_dir),
        "--warmup-s", str(exp.get("warmup_s", 0.001)),
        "--record-interval", str(exp.get("record_interval", 1)),
        "--skip-s", str(exp.get("skip_s", 0.0)),
    ]
    t0 = time.monotonic()
    with log_path.open("w") as logf:
        proc = subprocess.run(cmd, cwd=cocotb_root(), stdout=logf, stderr=subprocess.STDOUT)
    wall_s = time.monotonic() - t0

    metrics_path = out_dir / "metrics.json"
    metrics = load_json(metrics_path) if metrics_path.exists() else None
    return {"id": exp["id"], "ok": proc.returncode == 0, "wall_s": wall_s, "metrics": metrics, "out_dir": out_dir}


def _summary_row_from_result(exp: dict[str, Any], result: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    case = next(c for c in manifest["cases"] if c["id"] == exp["case_id"])
    m = (result.get("metrics") or {}).get("metrics", {})
    overlay_rel = f"{exp['output_dir']}/overlay.html"
    return {
        "case": exp["case_id"], "level": exp["level"].upper(),
        "status": "generated" if result["ok"] else "blocked",
        "path": exp["output_dir"],
        "duration_s": exp.get("duration_s", ""), "t_acc_s": case.get("t_acc_s", ""),
        "tload_nm": exp.get("tload_nm", ""),
        "csv_rows": (result.get("metrics") or {}).get("csv_rows", ""),
        "nrmse_i_alpha": m.get("nrmse_i_alpha", ""), "nrmse_i_beta": m.get("nrmse_i_beta", ""),
        "mae_flux_alpha_wb": m.get("mae_flux_alpha_wb", ""), "mae_flux_beta_wb": m.get("mae_flux_beta_wb", ""),
        "mae_speed_rad_s": m.get("mae_speed_rad_s", ""),
        "overlay": overlay_rel, "note": exp.get("description", ""),
    }


def _regenerate_dashboard(campaign_dir: Path) -> None:
    cmd = ["uv", "run", "python", "scripts/build_campaign_dashboard.py", "--campaign", str(campaign_dir)]
    subprocess.run(cmd, cwd=cocotb_root())


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--max-parallel", type=int, default=4)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    config = load_json(args.config)
    manifest = load_manifest(args.manifest)
    case_root = Path(config["case_root"])
    if not case_root.is_absolute():
        case_root = project_root() / case_root

    experiments = [e for e in config["experiments"] if e.get("enabled", False)]
    config["_experiments_by_id"] = {e["id"]: e for e in experiments}
    if args.only:
        experiments = [e for e in experiments if e["id"] in set(args.only)]

    if not args.force:
        experiments = [
            e for e in experiments
            if not _is_case_already_ok(manifest, e["case_id"], e["level"], e["result_key"])
        ]

    cocotb_exps = [e for e in experiments if e["runner"] == "cocotb"]
    mock_exps = [e for e in experiments if e["runner"] == "fullstack_mock"]

    if args.dry_run:
        for e in cocotb_exps + mock_exps:
            print(f"[dry-run] {e['id']} ({e['runner']}) -> {e['output_dir']}")
        return 0

    ensure_c_model_built()

    any_failed = False
    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        futures = {pool.submit(run_one_cocotb, config, e, case_root): e for e in cocotb_exps}
        for future in as_completed(futures):
            exp = futures[future]
            result = future.result()
            update_manifest_case(manifest, exp["case_id"], exp["level"], exp["result_key"],
                                  exp["output_dir"], ok=result["ok"])
            save_manifest(args.manifest, manifest)
            append_summary_row(args.summary, _summary_row_from_result(exp, result, manifest))
            status = "OK" if result["ok"] else "FAIL"
            print(f"[{status}] {exp['id']} ({result['wall_s']:.1f}s)", flush=True)
            if result["ok"] and exp["level"] == "l3":
                generate_l3_overlay(result["out_dir"], f"{exp['id']} - Top_HIL PWM replay vs C")
                write_readme(result["out_dir"], exp, result["metrics"], result["wall_s"], None)
            if not result["ok"]:
                any_failed = True

    for exp in mock_exps:
        dep = config["_experiments_by_id"][exp["depends_on"]]
        if not _is_case_already_ok(manifest, dep["case_id"], dep["level"], dep["result_key"]):
            print(f"[SKIP] {exp['id']} — dependencia {dep['id']} nao concluida", flush=True)
            any_failed = True
            continue
        result = run_one_fullstack_mock(config, exp, case_root)
        update_manifest_case(manifest, exp["case_id"], exp["level"], exp["result_key"],
                              exp["output_dir"], ok=result["ok"])
        save_manifest(args.manifest, manifest)
        append_summary_row(args.summary, _summary_row_from_result(exp, result, manifest))
        status = "OK" if result["ok"] else "FAIL"
        print(f"[{status}] {exp['id']} ({result['wall_s']:.1f}s)", flush=True)
        if not result["ok"]:
            any_failed = True

    _regenerate_dashboard(case_root)
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
