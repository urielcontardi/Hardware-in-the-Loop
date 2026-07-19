#!/usr/bin/env python3
"""Gera as figuras L2 (solver VHDL vs modelo C), dirigido por caso.

Uso (de verification/cocotb/):
    uv run python scripts/l2_figures.py                 # 3 casos S0 padrao
    uv run python scripts/l2_figures.py --case sine
    uv run python scripts/l2_figures.py --campaign ../results/... --out /tmp/figs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_common as cc  # noqa: E402  (load_csv_columns, inverse_clarke)

plt.rcParams.update({
    "font.family": "serif",
    "axes.grid": True,
    "grid.color": "#d9d9d9",
    "grid.linewidth": 0.5,
    "axes.edgecolor": "black",
    "figure.dpi": 120,
})

# Paleta Okabe-Ito (segura para daltonismo; validada com dataviz).
# Fases: VHDL solido, C tracejado.
PHASE_COLORS = ("#0072B2", "#E69F00", "#009E73")  # ia, ib, ic
COL_VHDL = "#0072B2"        # azul  — solido
COL_C = "#D55E00"           # vermillion — tracejado
COL_ERR_SPEED = "#CC79A7"   # roxo avermelhado (erro de velocidade)
VHDL_STYLE = {"linestyle": "-", "linewidth": 1.3}
REF_STYLE = {"linestyle": "--", "linewidth": 1.3, "alpha": 0.85}

# ── Caminhos ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_DIR = REPO_ROOT / "verification/results/2026-07-04_campaign_03/S0_tacc1s_load000"
DEFAULT_OUT = REPO_ROOT / "docs/results-chapter/figures/l2"

# ── Manifesto dos casos ───────────────────────────────────────────────────────
# tipo: "sine" (regime) ou "vf" (rampa). Define o conjunto de plots.
CASES = [
    {"id": "sine",  "dir": "l2_sine_60hz_realts", "csv": "sine_vhdl_vs_c.csv",
     "tipo": "sine", "label": "Seno 60 Hz",
     "zoom": [(1.0, 4.0, "Regime permanente", "#009E73")]},   # ms (ver t_ms)
    {"id": "vf50ms", "dir": "l2_vf_50ms_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 50 ms",
     "plots": ["overlay", "residual"],   # override: transitorio curto
     "zoom": []},
    {"id": "vf2s", "dir": "l2_vf_2s_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 2 s",
     "zoom": [(1900.0, 2000.0, "Regime permanente", "#009E73")],  # ms
     "windows_s": [(0.0, 0.05), (0.05, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]},
]

CSV_COLS = ["t_us",
            "vhdl_i_alpha", "vhdl_i_beta", "ref_i_alpha", "ref_i_beta",
            "vhdl_flux_alpha", "vhdl_flux_beta", "ref_flux_alpha", "ref_flux_beta",
            "vhdl_speed", "ref_speed"]

RAD_S_TO_RPM = 60.0 / (2.0 * np.pi)


# ── Métricas ──────────────────────────────────────────────────────────────────
def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


def _nrmse(ref: np.ndarray, vhdl: np.ndarray) -> float:
    denom = _rms(ref)
    return float(_rms(vhdl - ref) / denom) if denom > 1e-12 else float("nan")


def _r2(ref: np.ndarray, vhdl: np.ndarray) -> float:
    ss_res = float(np.sum((vhdl - ref) ** 2))
    ss_tot = float(np.sum((ref - np.mean(ref)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")


def _max_abs(ref: np.ndarray, vhdl: np.ndarray) -> float:
    return float(np.max(np.abs(vhdl - ref)))


def _mae(ref: np.ndarray, vhdl: np.ndarray) -> float:
    return float(np.mean(np.abs(vhdl - ref)))


def compute_metrics(data: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Recalcula NRMSE/R2/erro-max/MAE por sinal a partir das colunas do CSV."""
    def arr(k):
        return np.asarray(data[k], dtype=float)

    out: dict[str, dict[str, float]] = {}
    for sig in ("i_alpha", "i_beta"):
        ref, vhdl = arr(f"ref_{sig}"), arr(f"vhdl_{sig}")
        out[sig] = {"nrmse": _nrmse(ref, vhdl), "r2": _r2(ref, vhdl),
                    "max_abs": _max_abs(ref, vhdl)}
    for sig in ("flux_alpha", "flux_beta"):
        ref, vhdl = arr(f"ref_{sig}"), arr(f"vhdl_{sig}")
        out[sig] = {"mae": _mae(ref, vhdl), "r2": _r2(ref, vhdl),
                    "max_abs": _max_abs(ref, vhdl)}
    ref, vhdl = arr("ref_speed"), arr("vhdl_speed")
    out["speed"] = {"mae": _mae(ref, vhdl), "mae_rpm": _mae(ref, vhdl) * RAD_S_TO_RPM,
                    "r2": _r2(ref, vhdl), "max_abs": _max_abs(ref, vhdl)}
    return out


# ── Carregamento / gravação ───────────────────────────────────────────────────
def _fig_id(case: dict) -> str:
    return {"sine": "Sine", "vf50ms": "VF50ms", "vf2s": "VF2s"}.get(
        case["id"], case["id"].capitalize())


def load_case(case: dict, campaign: Path = CAMPAIGN_DIR) -> tuple[np.ndarray, dict]:
    csv_path = campaign / case["dir"] / case["csv"]
    data = cc.load_csv_columns(csv_path, CSV_COLS)
    t_ms = np.asarray(data["t_us"], dtype=float) * 1e-3
    return t_ms, data


def save_fig(fig, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


# ── Plots ─────────────────────────────────────────────────────────────────────
def plot_overlay(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """3 paineis: correntes trifasicas, modulo do fluxo, velocidade (VHDL vs C)."""
    t = t_ms / 1000.0  # s
    vhdl_i = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_i = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])

    def mag(a, b):
        a, b = np.asarray(a), np.asarray(b)
        return np.sqrt(a ** 2 + b ** 2)

    vhdl_flux = mag(data["vhdl_flux_alpha"], data["vhdl_flux_beta"])
    ref_flux = mag(data["ref_flux_alpha"], data["ref_flux_beta"])

    fig, axes = plt.subplots(3, 1, figsize=(7, 8), sharex=True)

    labels = ("$i_a$", "$i_b$", "$i_c$")
    for k in range(3):
        axes[0].plot(t, ref_i[k], color=PHASE_COLORS[k], **REF_STYLE)
        axes[0].plot(t, vhdl_i[k], color=PHASE_COLORS[k], label=labels[k], **VHDL_STYLE)
    axes[0].set_ylabel("Corrente [A]")
    axes[0].set_title(f"L2 — {case['label']}: correntes (— VHDL, - - C)")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    axes[1].plot(t, ref_flux, color=COL_C, **REF_STYLE, label="C")
    axes[1].plot(t, vhdl_flux, color=COL_VHDL, **VHDL_STYLE, label="VHDL")
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(t, np.asarray(data["ref_speed"]), color=COL_C, **REF_STYLE, label="C")
    axes[2].plot(t, np.asarray(data["vhdl_speed"]), color=COL_VHDL, **VHDL_STYLE, label="VHDL")
    axes[2].set_ylabel(r"$\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].legend(loc="upper right", fontsize=8)

    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Overlay")
