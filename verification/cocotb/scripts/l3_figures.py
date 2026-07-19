#!/usr/bin/env python3
"""Gera as figuras L3 (cadeia integrada Top_HIL vs modelo C), dirigido por caso.

Reutiliza o engine de `l2_figures.py` (metricas + plots), parametrizando coluna
de tempo (`t_s`), prefixo de referencia (`ref_` no PWM replay, `c_` no
full-stack), rotulos (Top_HIL vs C) e o prefixo de figura `HIL_L3`.

Dois modos de comparacao:
  - PWM replay  (l3_top_pwm_replay_*): Top_HIL vs C, ambos com o mesmo PWM.
  - Full-stack  (l3_fullstack_mock_*): Top_HIL vs C totalmente independente.

Uso (de verification/cocotb/):
    uv run python scripts/l3_figures.py
    uv run python scripts/l3_figures.py --case pwmreplay_vf2s
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import l2_figures as eng

CAMPAIGN_DIR = eng.CAMPAIGN_DIR
DEFAULT_OUT = eng.REPO_ROOT / "docs/results-chapter/figures/l3"

_LAB_REPLAY = {"dut": "Top_HIL", "ref": "C (replay)"}
_LAB_FULL = {"dut": "Top_HIL", "ref": "C indep."}
_PWM_COLS = ["va", "vb", "vc"]
_WINDOWS_2S = [(0.0, 0.05), (0.05, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]

# Base comum a todos os casos L3.
_L3_BASE = {"time_col": "t_s", "fig_prefix": "HIL_L3", "extra_cols": _PWM_COLS}


def _replay(cid, subdir, fig_id, label, tipo, **extra):
    return {**_L3_BASE, "id": cid, "dir": subdir, "csv": "top_pwm_replay_vs_c.csv",
            "ref_prefix": "ref", "labels": _LAB_REPLAY,
            "fig_id": fig_id, "label": label, "tipo": tipo, **extra}


def _fullstack(cid, subdir, fig_id, label, tipo, **extra):
    return {**_L3_BASE, "id": cid, "dir": subdir, "csv": "fullstack_vs_top.csv",
            "ref_prefix": "c", "labels": _LAB_FULL,
            "fig_id": fig_id, "label": label, "tipo": tipo, **extra}


CASES_L3 = [
    # ── PWM replay ────────────────────────────────────────────────────────────
    _replay("pwmreplay_sine6ms", "l3_top_pwm_replay_sine_6ms", "PWMreplay_Sine6ms",
            "PWM replay — Seno 6 ms", "vf",
            plots=["overlay", "residual", "pwm_stimulus"],
            pwm_zoom_ms=(0.0, 6.0)),
    _replay("pwmreplay_vf50ms", "l3_top_pwm_replay_vf_50ms", "PWMreplay_VF50ms",
            "PWM replay — V/f 50 ms", "vf",
            plots=["overlay", "residual", "pwm_stimulus"],
            pwm_zoom_ms=(25.0, 45.0)),
    _replay("pwmreplay_vf2s", "l3_top_pwm_replay_vf_2s", "PWMreplay_VF2s",
            "PWM replay — V/f 2 s", "vf",
            plots=["overlay", "lissajous", "residual", "phase_zoom",
                   "window_nrmse", "pwm_stimulus"],
            zoom=[(1900.0, 2000.0, "Regime permanente", "#009E73")],
            windows_s=_WINDOWS_2S, pwm_zoom_ms=(1900.0, 1920.0)),
    # ── Full-stack (C independente) ──────────────────────────────────────────
    _fullstack("fullstack_vf50ms", "l3_fullstack_mock_vf_50ms", "Fullstack_VF50ms",
               "Full-stack — V/f 50 ms", "vf",
               plots=["overlay", "residual", "pwm_stimulus"],
               pwm_zoom_ms=(25.0, 45.0)),
    _fullstack("fullstack_vf2s", "l3_fullstack_mock_vf_2s", "Fullstack_VF2s",
               "Full-stack — V/f 2 s", "vf",
               plots=["overlay", "lissajous", "residual", "phase_zoom",
                      "window_nrmse", "pwm_stimulus"],
               zoom=[(1900.0, 2000.0, "Regime permanente", "#009E73")],
               windows_s=_WINDOWS_2S, pwm_zoom_ms=(1900.0, 1920.0)),
]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Gera figuras L3 (Top_HIL vs C).")
    ap.add_argument("--campaign", type=Path, default=CAMPAIGN_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES_L3],
                    help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES_L3 if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = eng.generate_case(case, args.out, args.campaign)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l3_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"[ok] metricas em {args.out / 'l3_metrics.json'}")


if __name__ == "__main__":
    main()
