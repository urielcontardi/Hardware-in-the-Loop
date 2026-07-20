#!/usr/bin/env python3
"""Figuras dos Grupos A e B no estilo novo (Top_HIL vs modelo C, L3 PWM replay).

Reutiliza o engine de `l2_figures.py`. Substitui as antigas figuras
"CorrenteFluxoVelocidade" por overlay colorido + traço de erro, e o zoom-degrau
do Grupo B pelo recorte de fase em torno do degrau. Gera também a síntese
(NRMSE L2 vs L3 por caso) que substitui HIL_GrupoA03_Sintese.

Uso (de verification/cocotb/):
    uv run python scripts/grupoab_figures.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import l2_figures as eng

CAMP = eng.REPO_ROOT / "verification/results/2026-07-04_campaign_03"
DEFAULT_OUT = eng.REPO_ROOT / "docs/results-chapter/figures/grupoab"
_LAB = {"dut": "Top_HIL", "ref": "C (replay)"}
_STEP_COLOR = "#E69F00"

# id -> (case_dir, l2_sub, l3_sub, fig_id, label, tipo, zoom_ms, plots)
_A = [
    ("A1", "A1_tacc0p5s_load000", "l2_vf_500ms_realts", "l3_top_pwm_replay_vf_500ms",
     "GrupoA_A1", r"A1 — $t_{acc}$=0,5 s, vazio", [(450.0, 500.0, "Regime", "#009E73")]),
    ("A3", "A3_tacc1s_load050", "l2_vf_1s_realts", "l3_top_pwm_replay_vf_1s",
     "GrupoA_A3", r"A3 — $t_{acc}$=1 s, carga leve", [(900.0, 1000.0, "Regime", "#009E73")]),
    ("A5", "A5_tacc5s_load000", "l2_vf_5s_realts", "l3_top_pwm_replay_vf_5s",
     "GrupoA_A5", r"A5 — $t_{acc}$=5 s, vazio", [(4900.0, 5000.0, "Regime", "#009E73")]),
]
_B = [
    ("B1", "B1_step025_to075", "l2_step_1s", "l3_top_pwm_replay_step_1s",
     "GrupoB_B1", r"B1 — degrau 0,25$\rightarrow$0,75 $T_n$", True),
    ("B2", "B2_step050_to100", "l2_step_1s", "l3_top_pwm_replay_step_1s",
     "GrupoB_B2", r"B2 — degrau 0,50$\rightarrow$1,00 $T_n$", False),
]


def _case_a(cid, cdir, l2sub, l3sub, fig_id, label, zoom):
    # sem faixa de zoom no overlay: nao ha figura de zoom dos casos A no texto
    return {"id": cid, "dir": f"{cdir}/{l3sub}", "csv": "top_pwm_replay_vs_c.csv",
            "time_col": "t_s", "ref_prefix": "ref", "fig_prefix": "HIL_L3",
            "labels": _LAB, "fig_id": fig_id, "label": label, "tipo": "vf",
            "plots": ["overlay", "residual"]}


def _case_b(cid, cdir, l2sub, l3sub, fig_id, label, with_zoom):
    """B1 mostra o zoom do degrau (with_zoom=True); B2 so overlay+residuo."""
    c = {"id": cid, "dir": f"{cdir}/{l3sub}", "csv": "top_pwm_replay_vs_c.csv",
         "time_col": "t_s", "ref_prefix": "ref", "fig_prefix": "HIL_L3",
         "labels": _LAB, "fig_id": fig_id, "label": label, "tipo": "vf",
         "plots": ["overlay", "residual"]}
    if with_zoom:
        c["zoom"] = [(500.0, 700.0, "Degrau de carga", _STEP_COLOR)]
        c["plots"] = ["overlay", "residual", "phase_zoom"]
    return c


def _nrmse_pct(case_dir, sub):
    p = CAMP / case_dir / sub / "metrics.json"
    m = json.loads(p.read_text())["metrics"]
    return m["nrmse_i_alpha"] * 100.0


def plot_group_a_summary(out_dir: Path) -> None:
    """Barras de NRMSE de i_alpha (L2 vs L3) por caso do Grupo A."""
    plt = eng.plt
    ids = [a[0] for a in _A]
    l2 = [_nrmse_pct(a[1], a[2]) for a in _A]
    l3 = [_nrmse_pct(a[1], a[3]) for a in _A]
    x = np.arange(len(ids)); w = 0.38
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - w / 2, l2, w, color=eng.COL_VHDL, label="L2 (solver isolado)")
    ax.bar(x + w / 2, l3, w, color=eng.COL_C, label="L3 (cadeia integrada)")
    ax.set_xticks(x); ax.set_xticklabels(ids)
    ax.set_ylabel(r"NRMSE de $i_{s\alpha}$ [\%]".replace("\\%", "%"))
    ax.set_xlabel("Caso do Grupo A")
    ax.set_title("Síntese Grupo A: NRMSE de corrente, L2 vs L3")
    ax.legend(fontsize=9)
    eng.save_fig(fig, out_dir, "HIL_L3_GrupoA_Summary")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Gera figuras Grupo A/B (Top_HIL vs C).")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    cases = [_case_a(*a) for a in _A] + [_case_b(*b) for b in _B]
    for case in cases:
        eng.generate_case(case, args.out, CAMP)
    plot_group_a_summary(args.out)
    print(f"[ok] figuras Grupo A/B em {args.out}")


if __name__ == "__main__":
    main()
