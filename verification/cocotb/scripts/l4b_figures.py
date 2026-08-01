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


if __name__ == "__main__":
    pass
