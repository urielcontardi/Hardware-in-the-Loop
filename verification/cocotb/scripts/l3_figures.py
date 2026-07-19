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


def plot_phase_drift_comparison(replay_case: dict, full_case: dict, out_dir: Path,
                                campaign: Path = CAMPAIGN_DIR) -> dict:
    """Δφ(t) do PWM replay (travado ~0°) vs full-stack (rampa→platô).

    Figura-chave da narrativa: prova que a defasagem vem do gerador de ângulo V/f
    (acumula durante a rampa, congela em regime), não do solver.
    """
    import numpy as np
    plt = eng.plt

    def _trend(t_ms, drift, t0_s=0.05, win=201):
        """Suaviza (media movel com padding de borda) e corta o inicio (i~0)."""
        t = np.asarray(t_ms) / 1000.0
        d = np.asarray(drift, dtype=float)
        pad = win // 2
        ds = np.convolve(np.pad(d, pad, mode="edge"), np.ones(win) / win, "valid")[:len(d)]
        m = t >= t0_s
        return t[m], ds[m]

    def _plateau_deg(t_ms, drift):
        """Valor de regime robusto: mediana do Δφ no ultimo quarto (evita bordas)."""
        t = np.asarray(t_ms) / 1000.0
        d = np.asarray(drift, dtype=float)
        m = t >= 0.75 * float(t.max())
        return float(np.median(d[m]))

    tr, dr = eng.load_case(replay_case, campaign)
    tf, df = eng.load_case(full_case, campaign)
    raw_r, raw_f = eng.phase_drift_deg(dr), eng.phase_drift_deg(df)
    tr_s, drift_r = _trend(tr, raw_r)
    tf_s, drift_f = _trend(tf, raw_f)

    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.axhline(0.0, color="0.6", linewidth=0.7)
    ax.plot(tf_s, drift_f, color=eng.COL_C, linewidth=1.8,
            label="Full-stack (C independente)")
    ax.plot(tr_s, drift_r, color=eng.COL_VHDL, linewidth=1.8,
            label="PWM replay (mesmo estímulo)")
    # marca o fim da rampa (t_acc), onde o drift congela
    ax.axvline(1.0, color=eng.COL_ERR_SPEED, linestyle=":", linewidth=1.1)
    ax.annotate("fim da rampa V/f →\ndrift congela", xy=(1.0, 18.0),
                xytext=(1.28, 8.0), fontsize=8.5, color=eng.COL_ERR_SPEED,
                ha="left", va="center")
    ax.set_xlabel("Tempo [s]")
    ax.set_ylabel("Defasagem $\\Delta\\varphi$ [graus]")
    ax.set_title("L3 — defasagem da corrente ao longo do tempo (tendência)")
    ax.legend(loc="upper left", fontsize=9)
    eng.save_fig(fig, out_dir, "HIL_L3_PhaseDrift")
    return {"replay_end_deg": _plateau_deg(tr, raw_r),
            "fullstack_end_deg": _plateau_deg(tf, raw_f)}


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
        m = eng.generate_case(case, args.out, args.campaign)
        # anexa a analise de fase (regime = ultimo quarto) para o texto da tese
        t_ms, data = eng.load_case(case, args.campaign)
        m["phase"] = eng.phase_analysis(t_ms, data)
        all_metrics[case["id"]] = m

    # figura-chave: drift de fase replay vs full-stack (se ambos vf2s selecionados)
    ids = {c["id"] for c in selected}
    if {"pwmreplay_vf2s", "fullstack_vf2s"} <= ids:
        rep = next(c for c in CASES_L3 if c["id"] == "pwmreplay_vf2s")
        full = next(c for c in CASES_L3 if c["id"] == "fullstack_vf2s")
        info = plot_phase_drift_comparison(rep, full, args.out, args.campaign)
        print(f"[ok] drift: replay={info['replay_end_deg']:+.1f}deg  "
              f"full-stack={info['fullstack_end_deg']:+.1f}deg")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l3_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"[ok] metricas em {args.out / 'l3_metrics.json'}")


if __name__ == "__main__":
    main()
