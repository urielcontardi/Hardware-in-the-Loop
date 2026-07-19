#!/usr/bin/env python3
"""Gera as figuras L4 (FPGA real vs modelo C), dirigido por caso.

Fonte: capturas .hilbin reais de bancada, já processadas por `hilbin_vs_c.py`
para .npz alinhados (fpga_* vs cmod_*), em dois segmentos: `partida` e `regime`.
Reutiliza o engine de `l2_figures.py` mapeando as correntes de fase (ia, ib) e o
fluxo/velocidade para as chaves canônicas vhdl_*/ref_*.

Uso (de verification/cocotb/):
    uv run python scripts/l4_figures.py
    uv run python scripts/l4_figures.py --case S0 --case B1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import l2_figures as eng

CAMPAIGN_L4 = eng.REPO_ROOT / "verification/results/2026-07-14_campaign_l4"
DEFAULT_OUT = eng.REPO_ROOT / "docs/results-chapter/figures/l4"

_LAB = {"dut": "FPGA (real)", "ref": "Modelo C"}
_SEG_NAME = {"partida": "Partida", "regime": "Regime"}
SEGMENTS = ("partida", "regime")

CASES_L4 = [
    {"id": "S0", "dir": "S0_l4", "label": "S0 — t$_{acc}$=1 s, vazio"},
    {"id": "A1", "dir": "A1_l4", "label": "A1 — t$_{acc}$=0,5 s, vazio"},
    {"id": "A3", "dir": "A3_l4", "label": "A3 — t$_{acc}$=1 s, carga leve"},
    {"id": "A5", "dir": "A5_l4", "label": "A5 — t$_{acc}$=5 s, vazio"},
    {"id": "B1", "dir": "B1_l4", "label": "B1 — degrau 0,25→0,75 T$_n$"},
    {"id": "B2", "dir": "B2_l4", "label": "B2 — degrau 0,50→1,00 T$_n$"},
]


def _npz_path(case: dict, seg: str, campaign: Path) -> Path:
    return campaign / case["dir"] / "l4_pwm_replay/capture" / f"{seg}.npz"


def load_segment(case: dict, seg: str, campaign: Path = CAMPAIGN_L4) -> tuple[np.ndarray, dict]:
    """Carrega o .npz de um segmento e mapeia p/ as chaves canônicas do engine.

    Correntes vêm em fase (ia, ib); reconstroi α/β por Clarke direta para que os
    plots do engine (que fazem Clarke inversa) reproduzam ia/ib/ic corretamente.
    Fluxo já vem em α/β (flux_a/flux_b).
    """
    d = np.load(_npz_path(case, seg, campaign))
    s3 = np.sqrt(3.0)

    def clarke_beta(ia, ib):
        return (np.asarray(ia) + 2.0 * np.asarray(ib)) / s3

    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"]),
        "vhdl_i_beta": clarke_beta(d["fpga_ia"], d["fpga_ib"]),
        "ref_i_alpha": np.asarray(d["cmod_ia"]),
        "ref_i_beta": clarke_beta(d["cmod_ia"], d["cmod_ib"]),
        "vhdl_flux_alpha": np.asarray(d["fpga_flux_a"]),
        "vhdl_flux_beta": np.asarray(d["fpga_flux_b"]),
        "ref_flux_alpha": np.asarray(d["cmod_flux_a"]),
        "ref_flux_beta": np.asarray(d["cmod_flux_b"]),
        "vhdl_speed": np.asarray(d["fpga_speed"]),
        "ref_speed": np.asarray(d["cmod_speed"]),
    }
    t_ms = np.asarray(d["fpga_t"], dtype=float) * 1000.0
    return t_ms, data


def _seg_case(case: dict, seg: str) -> dict:
    return {"id": case["id"], "tipo": "vf", "fig_prefix": "HIL_L4", "labels": _LAB,
            "fig_id": f"{case['id']}_{_SEG_NAME[seg]}",
            "label": f"{case['label']} · {_SEG_NAME[seg]}"}


def generate_case_l4(case: dict, out_dir: Path, campaign: Path = CAMPAIGN_L4) -> dict:
    metrics: dict[str, dict] = {}
    for seg in SEGMENTS:
        if not _npz_path(case, seg, campaign).is_file():
            continue
        t_ms, data = load_segment(case, seg, campaign)
        c = _seg_case(case, seg)
        eng.plot_overlay(t_ms, data, c, out_dir)
        eng.plot_residual(t_ms, data, c, out_dir)
        if seg == "regime":
            eng.plot_lissajous(t_ms, data, c, out_dir)  # trajetória real vs C
        metrics[seg] = eng.compute_metrics(data)
    print(f"[ok] {case['id']}: figuras L4 em {out_dir}")
    return metrics


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Gera figuras L4 (FPGA real vs C).")
    ap.add_argument("--campaign", type=Path, default=CAMPAIGN_L4)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES_L4],
                    help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES_L4 if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = generate_case_l4(case, args.out, args.campaign)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l4_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"[ok] metricas em {args.out / 'l4_metrics.json'}")


if __name__ == "__main__":
    main()
