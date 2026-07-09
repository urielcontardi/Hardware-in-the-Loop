#!/usr/bin/env python3
"""Run reproducible cocotb validation campaigns.

Edit a JSON file in ``verification/cocotb/campaigns`` and run:

    cd verification/cocotb
    uv run python scripts/run_campaign.py --config campaigns/l3_pwm_replay.json

The runner creates one result directory per enabled experiment, runs cocotb with
consistent environment variables, generates an interactive HTML overlay for L3
PWM-replay CSV files, writes a README, and updates a campaign summary JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def cocotb_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def env_number(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def build_l3_env(config: dict[str, Any], exp: dict[str, Any], out_dir: Path) -> dict[str, str]:
    defaults = config.get("defaults", {})
    motor = defaults.get("motor", {})
    clock = int(defaults.get("im_clock_frequency", 200_000_000))
    step_cycles = int(defaults.get("im_solver_step_cycles", 26))
    ts = step_cycles / clock
    if "steps" in exp:
        steps = int(exp["steps"])
    else:
        steps = int(round(float(exp["duration_s"]) / ts))

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
        "HIL_PWM_FREQUENCY": env_number(defaults.get("hil_pwm_frequency", 1000)),
        "HIL_UART_BAUD": env_number(defaults.get("hil_uart_baud", 1_000_000)),
        "HIL_L3_STEPS": env_number(steps),
        "HIL_L3_WARMUP_STEPS": env_number(exp.get("warmup_steps", 400)),
        "HIL_L3_RECORD_INTERVAL": env_number(exp.get("record_interval", 1)),
        "HIL_L3_VDC": env_number(exp.get("vdc", defaults.get("vdc", 1240.0))),
        "HIL_L3_MODULATION": env_number(exp.get("modulation", 1.0)),
        "HIL_L3_REF_MODE": str(exp.get("ref_mode", "vf")),
        "HIL_L3_REF_FREQ_HZ": env_number(exp.get("ref_freq_hz", 60.0)),
        "HIL_L3_VF_BASE_HZ": env_number(exp.get("vf_base_hz", 60.0)),
        "HIL_L3_VF_ACC_HZ_S": env_number(exp.get("vf_acc_hz_s", 60.0)),
        "HIL_L3_INITIAL_THETA_RAD": env_number(exp.get("initial_theta_rad", defaults.get("initial_theta_rad", math.pi / 4))),
        "HIL_L3_TLOAD_NM": env_number(exp.get("tload_nm", defaults.get("tload_nm", 0.0))),
        "HIL_L3_OUT_DIR": str(out_dir.resolve()),
    })
    if "tload_step_nm" in exp and "tload_step_time_s" in exp:
        env["HIL_L3_TLOAD_STEP_NM"] = env_number(exp["tload_step_nm"])
        env["HIL_L3_TLOAD_STEP_TIME_S"] = env_number(exp["tload_step_time_s"])
    return env


def run_cocotb(exp: dict[str, Any], env: dict[str, str], build_dir: str = "sim_build",
               log_file: Any = None) -> int:
    cmd = [
        "uv", "run", "python", "run.py",
        "--sim", str(exp.get("sim", "nvc")),
        "--top", str(exp.get("top", "top_hil")),
        "--build-dir", build_dir,
    ]
    test_mode = exp.get("test_mode")
    if test_mode:
        cmd.extend(["--test", str(test_mode)])
    testcase = exp.get("testcase")
    if testcase:
        cmd.extend(["-k", str(testcase)])
    if log_file is not None:
        print("[campaign] running:", " ".join(cmd), file=log_file, flush=True)
        proc = subprocess.run(cmd, cwd=cocotb_root(), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    else:
        print("[campaign] running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=cocotb_root(), env=env)
    return proc.returncode


def read_csv_rows(csv_path: Path, max_points: int = 14000) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        all_rows = [{k: float(v) for k, v in r.items()} for r in reader]
    if not all_rows:
        return []
    stride = max(1, len(all_rows) // max_points)
    return all_rows[::stride]


def generate_l3_overlay(out_dir: Path, title: str) -> Path | None:
    csv_path = out_dir / "top_pwm_replay_vs_c.csv"
    if not csv_path.exists():
        return None
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception as exc:
        print(f"[campaign] plotly unavailable, skipping overlay: {exc}", flush=True)
        return None

    rows = read_csv_rows(csv_path)
    if not rows:
        return None
    t = [r["t_s"] * 1e3 for r in rows]
    fig = make_subplots(
        rows=7,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=[
            "i_alpha", "i_beta", "flux alpha", "flux beta", "speed",
            "instantaneous switched va/vb/vc", "PWM state A/B/C",
        ],
    )

    def tr(y, name, color, row, dash="solid", width=1.2):
        fig.add_trace(
            go.Scatter(x=t, y=y, name=name, line=dict(color=color, width=width, dash=dash)),
            row=row,
            col=1,
        )

    tr([r["ref_i_alpha"] for r in rows], "C i_alpha", "#2f80ed", 1)
    tr([r["vhdl_i_alpha"] for r in rows], "Top_HIL i_alpha", "#ff6b35", 1, "dot")
    tr([r["ref_i_beta"] for r in rows], "C i_beta", "#2f80ed", 2)
    tr([r["vhdl_i_beta"] for r in rows], "Top_HIL i_beta", "#ff6b35", 2, "dot")
    tr([r["ref_flux_alpha"] for r in rows], "C flux alpha", "#2f80ed", 3)
    tr([r["vhdl_flux_alpha"] for r in rows], "Top_HIL flux alpha", "#ff6b35", 3, "dot")
    tr([r["ref_flux_beta"] for r in rows], "C flux beta", "#2f80ed", 4)
    tr([r["vhdl_flux_beta"] for r in rows], "Top_HIL flux beta", "#ff6b35", 4, "dot")
    tr([r["ref_speed"] for r in rows], "C speed", "#2f80ed", 5)
    tr([r["vhdl_speed"] for r in rows], "Top_HIL speed", "#ff6b35", 5, "dot")
    tr([r["va"] for r in rows], "va", "#2f80ed", 6)
    tr([r["vb"] for r in rows], "vb", "#27ae60", 6)
    tr([r["vc"] for r in rows], "vc", "#9b51e0", 6)
    tr([r["pwm_a"] for r in rows], "pwm_a", "#2f80ed", 7)
    tr([r["pwm_b"] for r in rows], "pwm_b", "#27ae60", 7)
    tr([r["pwm_c"] for r in rows], "pwm_c", "#9b51e0", 7)

    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=1450,
        legend=dict(orientation="h", y=1.035),
        font=dict(size=12),
    )
    for i in range(1, 8):
        fig.update_xaxes(gridcolor="#233142", row=i, col=1)
        fig.update_yaxes(gridcolor="#233142", row=i, col=1)
    fig.update_xaxes(title_text="time [ms]", row=7, col=1)
    out = out_dir / "overlay.html"
    fig.write_html(str(out), include_plotlyjs="cdn")
    return out


def write_readme(out_dir: Path, exp: dict[str, Any], metrics: dict[str, Any] | None, wall_s: float, overlay: Path | None) -> None:
    m = (metrics or {}).get("metrics", {})
    lines = [
        f"# {exp['id']}",
        "",
        exp.get("description", "Cocotb campaign experiment."),
        "",
        "## Execucao",
        "",
        f"- Status: `{(metrics or {}).get('status', 'unknown')}`.",
        f"- Tempo de parede: `{wall_s:.1f} s` (`{wall_s/3600:.2f} h`).",
        f"- Tempo fisico simulado: `{(metrics or {}).get('duration_s', exp.get('duration_s', 'unknown'))}` s.",
        f"- Linhas CSV: `{(metrics or {}).get('csv_rows', 'unknown')}`.",
        f"- Amostras usadas nas metricas: `{(metrics or {}).get('metrics_samples', 'unknown')}`.",
        f"- Record interval: `{(metrics or {}).get('record_interval', exp.get('record_interval', 1))}`.",
        "",
        "## Metricas",
        "",
        f"- `i_alpha` NRMSE: `{m.get('nrmse_i_alpha', 'n/a')}`.",
        f"- `i_beta` NRMSE: `{m.get('nrmse_i_beta', 'n/a')}`.",
        f"- `flux_alpha` MAE: `{m.get('mae_flux_alpha_wb', 'n/a')}` Wb.",
        f"- `flux_beta` MAE: `{m.get('mae_flux_beta_wb', 'n/a')}` Wb.",
        f"- velocidade MAE: `{m.get('mae_speed_rad_s', 'n/a')}` rad/s.",
        "",
        "## Arquivos",
        "",
        "- `metrics.json`: parametros e metricas.",
        "- `top_pwm_replay_vs_c.csv`: CSV decimado para inspecao visual.",
        "- `overlay.html`: grafico interativo." if overlay else "- `overlay.html`: nao gerado.",
        "",
        "## Observacao",
        "",
        "Este e um L3 PWM replay: o C/C++ recebe `va/vb/vc` instantaneos do caminho interno do `Top_HIL`. O L3 full-stack final ainda deve gerar portadora/gate driver tambem no C/C++.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines))


def update_summary(config: dict[str, Any], exp: dict[str, Any], out_dir: Path, rc: int, wall_s: float) -> None:
    root = project_root() / config["case_root"]
    summary_path = root / "campaign_run_summary.json"
    if summary_path.exists():
        summary = load_json(summary_path)
    else:
        summary = {"updated_at": None, "runs": []}
    summary["updated_at"] = datetime.now(timezone.utc).isoformat()
    summary["runs"].append({
        "id": exp["id"],
        "returncode": rc,
        "wall_time_s": wall_s,
        "out_dir": str(out_dir.relative_to(project_root())),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    summary_path.write_text(json.dumps(summary, indent=2))


def run_experiment(config: dict[str, Any], exp: dict[str, Any]) -> int:
    case_root = project_root() / config["case_root"]
    out_dir = case_root / exp["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    env = build_l3_env(config, exp, out_dir)

    effective = {
        "experiment": exp,
        "environment": {k: env[k] for k in sorted(env) if k.startswith("IM_") or k.startswith("HIL_")},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "run_config_resolved.json").write_text(json.dumps(effective, indent=2))

    build_dir = exp.get("build_dir", f"sim_build/{exp['id']}")
    t0 = time.monotonic()
    rc = run_cocotb(exp, env, build_dir=build_dir)
    wall_s = time.monotonic() - t0

    metrics_path = out_dir / "metrics.json"
    metrics = load_json(metrics_path) if metrics_path.exists() else None
    overlay = None
    if rc == 0:
        overlay = generate_l3_overlay(out_dir, f"{exp['id']} - Top_HIL PWM replay vs C")
    write_readme(out_dir, exp, metrics, wall_s, overlay)
    update_summary(config, exp, out_dir, rc, wall_s)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--only", action="append", default=[], help="Run only experiment id; can be repeated")
    args = ap.parse_args()
    config_path = args.config if args.config.is_absolute() else cocotb_root() / args.config
    config = load_json(config_path)
    selected = set(args.only)
    rc_any = 0
    for exp in config.get("experiments", []):
        if not exp.get("enabled", False):
            continue
        if selected and exp["id"] not in selected:
            continue
        print(f"[campaign] === {exp['id']} ===", flush=True)
        rc = run_experiment(config, exp)
        if rc != 0:
            rc_any = rc
            print(f"[campaign] experiment failed: {exp['id']} rc={rc}", flush=True)
            break
    return rc_any


if __name__ == "__main__":
    raise SystemExit(main())
