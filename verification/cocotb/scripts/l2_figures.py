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


def _subsample(n: int, target: int = 5000) -> slice:
    step = max(1, n // target)
    return slice(None, None, step)


def plot_lissajous(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Trajetoria espaco-vetorial i_beta x i_alpha (VHDL vs C)."""
    s = _subsample(len(t_ms))
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(np.asarray(data["ref_i_alpha"])[s], np.asarray(data["ref_i_beta"])[s],
            color=COL_C, label="C", **REF_STYLE)
    ax.plot(np.asarray(data["vhdl_i_alpha"])[s], np.asarray(data["vhdl_i_beta"])[s],
            color=COL_VHDL, label="VHDL", **VHDL_STYLE)
    ax.set_xlabel(r"$i_\alpha$ [A]")
    ax.set_ylabel(r"$i_\beta$ [A]")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(f"L2 — {case['label']}: trajetória $i_\\beta \\times i_\\alpha$")
    ax.legend(loc="upper right", fontsize=9)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Lissajous")


def plot_phase_zoom(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Corrente ia completa + regioes sombreadas + paineis de zoom (estilo L1)."""
    t = t_ms / 1000.0  # s
    vhdl_ia = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0]
    ref_ia = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0]
    vhdl_ia, ref_ia = np.asarray(vhdl_ia), np.asarray(ref_ia)

    zooms = case.get("zoom", [])
    nz = len(zooms)
    fig, axes = plt.subplots(1 + nz, 1, figsize=(8, 3 + 2.2 * nz))
    if nz == 0:
        axes = [axes]
    top = axes[0]
    top.plot(t, ref_ia, color=COL_C, label="$i_a$ (C)", **REF_STYLE)
    top.plot(t, vhdl_ia, color=COL_VHDL, label="$i_a$ (VHDL)", **VHDL_STYLE)
    for (a_ms, b_ms, lbl, col) in zooms:
        top.axvspan(a_ms / 1000.0, b_ms / 1000.0, color=col, alpha=0.15, label=lbl)
    top.set_ylabel("$i_a$ [A]")
    top.set_xlabel("Tempo [s]")
    top.set_title(f"L2 — {case['label']}: visão completa e zoom")
    top.legend(loc="upper right", fontsize=8)

    for ax, (a_ms, b_ms, lbl, col) in zip(axes[1:], zooms):
        a, b = a_ms / 1000.0, b_ms / 1000.0
        mask = (t >= a) & (t <= b)
        ax.plot(t[mask], ref_ia[mask], color=COL_C, label="C", **REF_STYLE)
        ax.plot(t[mask], vhdl_ia[mask], color=COL_VHDL, label="VHDL", **VHDL_STYLE)
        ax.set_title(f"{lbl}: {a_ms:.0f}–{b_ms:.0f} ms", fontsize=10)
        ax.set_ylabel("$i_a$ [A]")
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("Tempo [s]")
    fig.tight_layout()
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_PhaseZoom")


def plot_residual(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Traco de erro epsilon(t)=VHDL-C: correntes de fase e velocidade."""
    t = t_ms / 1000.0
    vhdl_i = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_i = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])
    labels = ("$\\varepsilon_{i_a}$", "$\\varepsilon_{i_b}$", "$\\varepsilon_{i_c}$")

    fig, axes = plt.subplots(2, 1, figsize=(7, 5), sharex=True)
    for k in range(3):
        err = np.asarray(vhdl_i[k]) - np.asarray(ref_i[k])
        axes[0].plot(t, err, color=PHASE_COLORS[k], linewidth=0.9, label=labels[k])
    axes[0].axhline(0.0, color="0.5", linewidth=0.6)
    axes[0].set_ylabel("Erro corrente [A]")
    axes[0].set_title(f"L2 — {case['label']}: erro VHDL − C")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    err_w = np.asarray(data["vhdl_speed"]) - np.asarray(data["ref_speed"])
    axes[1].plot(t, err_w, color=COL_ERR_SPEED, linewidth=1.0, label=r"$\varepsilon_\omega$")
    axes[1].axhline(0.0, color="0.5", linewidth=0.6)
    axes[1].set_ylabel("Erro veloc. [rad/s]")
    axes[1].set_xlabel("Tempo [s]")
    axes[1].legend(loc="upper right", fontsize=8)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Residual")


def plot_window_nrmse(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """NRMSE de i_alpha/i_beta por janela temporal (barras)."""
    t_s = t_ms / 1000.0
    windows = case.get("windows_s", [])
    ia_ref, ia_vhdl = np.asarray(data["ref_i_alpha"]), np.asarray(data["vhdl_i_alpha"])
    ib_ref, ib_vhdl = np.asarray(data["ref_i_beta"]), np.asarray(data["vhdl_i_beta"])

    nrmse_a, nrmse_b, xlabels = [], [], []
    for (a, b) in windows:
        m = (t_s >= a) & (t_s < b)
        if not np.any(m):
            nrmse_a.append(0.0); nrmse_b.append(0.0)
        else:
            nrmse_a.append(_nrmse(ia_ref[m], ia_vhdl[m]) * 100.0)
            nrmse_b.append(_nrmse(ib_ref[m], ib_vhdl[m]) * 100.0)
        xlabels.append(f"{a:g}–{b:g}")

    x = np.arange(len(windows))
    w = 0.4
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - w / 2, nrmse_a, w, color=PHASE_COLORS[0], label=r"$i_\alpha$")
    ax.bar(x + w / 2, nrmse_b, w, color=PHASE_COLORS[1], label=r"$i_\beta$")
    ax.set_xticks(x); ax.set_xticklabels(xlabels)
    ax.set_xlabel("Janela [s]")
    ax.set_ylabel("NRMSE [%]")
    ax.set_title(f"L2 — {case['label']}: NRMSE por janela")
    ax.legend(fontsize=9)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_WindowNRMSE")
