#!/usr/bin/env python3
"""Gera figuras L4-B: FPGA real vs. reprodução independente completa em PSIM
(motor de indução nativo do PSIM, nao o modelo C/DLL embutido no mesmo
schematic). Ve docs/superpowers/specs/2026-08-01-l4b-psim-validacao-independente-design.md.

Le os .npz ja mesclados (fpga_*/psim_*, ver psim_csv_to_npz.py) para as
figuras de janela (partida/regime), e le o .hilbin bruto + o CSV bruto do
PSIM para a figura de visao geral (janela completa).

psim_ia/psim_ib sao um par alpha/beta (ver psim_csv_to_npz.py), nao fase
crua -- toda figura trifasica aplica chapter_common.inverse_clarke() neles,
igual ja e feito para fpga_ia/fpga_ib.

Sem painel de fluxo: o motor nativo do PSIM nao expoe fluxo do rotor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l2_figures as eng                # noqa: E402
import chapter_common as cc              # noqa: E402
import hilbin_vs_c as H                  # noqa: E402
import psim_csv_to_npz as psim_mod       # noqa: E402


def _overlap_mask_and_grid(fpga_t: np.ndarray, psim_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Clip fpga_t to the range where psim_t also has data.

    Returns (mask, t_common): mask selects into any array sampled on the
    fpga_t grid, t_common = fpga_t[mask].
    """
    t_lo = max(float(fpga_t.min()), float(psim_t.min()))
    t_hi = min(float(fpga_t.max()), float(psim_t.max()))
    mask = (fpga_t >= t_lo) & (fpga_t <= t_hi)
    return mask, fpga_t[mask]


def load_l4b_segment(case: dict, seg: str, campaign: Path) -> tuple[np.ndarray, dict]:
    """Load one partida/regime .npz, align PSIM onto the FPGA/C time grid.

    Returns (t_ms, data): data has vhdl_i_alpha/vhdl_i_beta/vhdl_speed
    (FPGA, clipped to PSIM's coverage) and ref_i_alpha/ref_i_beta/ref_speed
    (PSIM, interpolated onto the clipped FPGA grid).
    """
    npz_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / f"{seg}.npz"
    d = np.load(npz_path)
    fpga_t = np.asarray(d["fpga_t"], dtype=float)
    psim_t = np.asarray(d["psim_t"], dtype=float)
    mask, t_common = _overlap_mask_and_grid(fpga_t, psim_t)
    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"])[mask],
        "vhdl_i_beta": np.asarray(d["fpga_ib"])[mask],
        "vhdl_speed": np.asarray(d["fpga_speed"])[mask],
        "ref_i_alpha": np.interp(t_common, psim_t, np.asarray(d["psim_ia"])),
        "ref_i_beta": np.interp(t_common, psim_t, np.asarray(d["psim_ib"])),
        "ref_speed": np.interp(t_common, psim_t, np.asarray(d["psim_speed"])),
    }
    t_ms = t_common * 1000.0
    return t_ms, data


def _nrmse_pct(dut: np.ndarray, ref: np.ndarray) -> float:
    """RMSE(dut-ref) normalized by the peak-to-peak range of ref, as a percentage."""
    rmse = float(np.sqrt(np.mean((dut - ref) ** 2)))
    span = float(np.ptp(ref))
    return 100.0 * rmse / span if span > 0 else float("nan")


def _mae(dut: np.ndarray, ref: np.ndarray) -> float:
    return float(np.mean(np.abs(dut - ref)))


def compute_metrics_l4b(data: dict) -> dict[str, float]:
    """NRMSE (%) for i_alpha/i_beta, MAE for speed. No flux metric: the PSIM
    native motor block doesn't expose rotor flux."""
    return {
        "nrmse_i_alpha_pct": _nrmse_pct(data["vhdl_i_alpha"], data["ref_i_alpha"]),
        "nrmse_i_beta_pct": _nrmse_pct(data["vhdl_i_beta"], data["ref_i_beta"]),
        "mae_speed_rad_s": _mae(data["vhdl_speed"], data["ref_speed"]),
    }


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}\\%"


def _fmt_sci(x: float) -> str:
    return f"{x:.3g}"


def render_l4b_table(all_metrics: dict[str, dict[str, dict[str, float]]]) -> str:
    """Table-body fragment only (no \\begin{table}/\\caption/\\label wrapper --
    those are hand-written in 4-Resultados.tex, matching tab:l4-metricas'
    style; see chapter_tables.py::_render_metricas_table for the sibling
    pattern this mirrors)."""
    lines = [
        "\\begin{tabular}{l" + "c" * 6 + "}",
        "\\toprule",
        " & \\multicolumn{3}{c}{Partida} & \\multicolumn{3}{c}{Regime} \\\\",
        "Caso & $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] "
        "& $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] \\\\",
        "\\midrule",
    ]
    for case_id, windows in all_metrics.items():
        p = windows.get("partida", {})
        r = windows.get("regime", {})
        cells = [
            _fmt_pct(p.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(p.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(p.get("mae_speed_rad_s", float("nan"))),
            _fmt_pct(r.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(r.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(r.get("mae_speed_rad_s", float("nan"))),
        ]
        lines.append(f"{case_id} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    pass
