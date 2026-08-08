#!/usr/bin/env python3
"""Figuras do Capítulo 4 orientadas à evidência experimental.

Este módulo não substitui os geradores de diagnóstico. Ele produz um conjunto
menor de figuras para publicação: cada composição responde a uma pergunta do
texto e escolhe a janela a partir do evento físico do ensaio.

Uso (a partir de verification/cocotb/):
    uv run python scripts/publication_figures.py
    uv run python scripts/publication_figures.py --case A3 --case B1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import chapter_common as cc
import l2_figures as eng
import l4b_figures as l4b


STARTUP_TACC_S = {"S0": 1.0, "A1": 0.5, "A3": 1.0, "A5": 5.0}
COL_FPGA = eng.COL_VHDL
COL_REF = eng.COL_C
COL_ERROR = eng.COL_ERR_SPEED


def moving_rms(t: np.ndarray, y: np.ndarray, frequency_hz: float = 60.0) -> np.ndarray:
    """Envelope RMS de um ciclo, preservando o comprimento da série."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(t) < 3:
        return np.abs(y)
    dt = float(np.median(np.diff(t)))
    samples = max(3, int(round(1.0 / (frequency_hz * dt))))
    kernel = np.ones(samples, dtype=float) / samples
    left = samples // 2
    right = samples - 1 - left
    squared = np.pad(y * y, (left, right), mode="edge")
    return np.sqrt(np.convolve(squared, kernel, mode="valid"))


def _clip(data: dict[str, np.ndarray], start: float, end: float) -> dict[str, np.ndarray]:
    mask = (data["t"] >= start) & (data["t"] <= end)
    if not np.any(mask):
        raise ValueError(f"janela {start:g}–{end:g} s não intersecta os dados")
    return {key: np.asarray(value)[mask] for key, value in data.items()}


def _common(case: dict, campaign: Path, start: float, end: float):
    fpga = _clip(l4b.load_full_fpga_l4b(case, campaign), start, end)
    psim = _clip(l4b.load_full_psim_l4b(case, eng.REPO_ROOT), start, end)
    speed_ref = np.interp(fpga["t"], psim["t"], psim["speed"])
    return fpga, psim, speed_ref


def _style_axes(axes) -> None:
    for ax in np.atleast_1d(axes):
        ax.grid(True, color="#d9d9d9", linewidth=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=9)


def plot_startup(case: dict, campaign: Path, out_dir: Path) -> Path:
    """Evidência da partida: velocidade, corrente RMS e erro mecânico."""
    t_acc = STARTUP_TACC_S[case["id"]]
    end = t_acc + (0.30 if t_acc >= 5.0 else 0.25)
    fpga, psim, speed_ref = _common(case, campaign, 0.0, end)

    fpga_rms = moving_rms(fpga["t"], fpga["ia"])
    psim_rms = moving_rms(psim["t"], psim["ia"])
    speed_error = fpga["speed"] - speed_ref
    metric_end = min(0.5, t_acc)
    metric_mask = fpga["t"] <= metric_end
    mae = float(np.mean(np.abs(speed_error[metric_mask])))

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.25, 1.0, 0.8]})
    _style_axes(axes)

    axes[0].plot(fpga["t"], fpga["speed"], color=COL_FPGA, linewidth=1.8,
                 label="FPGA (real)")
    axes[0].plot(psim["t"], psim["speed"], color=COL_REF, linewidth=1.35,
                 linestyle="--", label="PSIM (independente)")
    axes[0].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[0].legend(loc="best", fontsize=8.5, framealpha=0.95)

    axes[1].plot(fpga["t"], fpga_rms, color=COL_FPGA, linewidth=1.7)
    axes[1].plot(psim["t"], psim_rms, color=COL_REF, linewidth=1.3, linestyle="--")
    axes[1].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")

    axes[2].plot(fpga["t"], speed_error, color=COL_ERROR, linewidth=1.25)
    axes[2].axhline(0.0, color="0.35", linewidth=0.7)
    axes[2].set_ylabel(r"$\Delta\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].text(0.985, 0.88, f"MAE (0–{metric_end:g} s) = {mae:.3g} rad/s",
                 transform=axes[2].transAxes,
                 ha="right", va="top", fontsize=8.5,
                 bbox={"facecolor": "white", "edgecolor": "0.75", "pad": 2.5})

    for ax in axes:
        ax.axvline(t_acc, color="black", linestyle=":", linewidth=1.0)
    axes[0].annotate(r"fim da rampa $t_{acc}$", xy=(t_acc, axes[0].get_ylim()[1]),
                     xytext=(-5, -5), textcoords="offset points", ha="right",
                     va="top", fontsize=8.5)
    axes[-1].set_xlim(0.0, end)
    fig.tight_layout(h_pad=0.35)
    name = f"HIL_L4B_{case['id']}_Evidence"
    eng.save_fig(fig, out_dir, name)
    return out_dir / f"{name}.pdf"


def plot_load_step(case: dict, campaign: Path, out_dir: Path) -> Path:
    """Evidência do degrau: corrente RMS, velocidade e torque aplicado."""
    meta_path = campaign / case["dir"] / "l4_pwm_replay/capture/metrics.json"
    tload = json.loads(meta_path.read_text())["tload"]
    step = float(tload["t_step_s"])
    start, end = step - 0.15, step + 0.15
    fpga, psim, _speed_ref = _common(case, campaign, start, end)

    fpga_rms = moving_rms(fpga["t"], fpga["ia"])
    psim_rms = moving_rms(psim["t"], psim["ia"])
    torque = np.where(fpga["t"] < step, float(tload["pre"]), float(tload["post"]))

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.1), sharex=True,
                             gridspec_kw={"height_ratios": [1.0, 1.2, 0.65]})
    _style_axes(axes)
    axes[0].plot(fpga["t"], fpga_rms, color=COL_FPGA, linewidth=1.7,
                 label="FPGA (real)")
    axes[0].plot(psim["t"], psim_rms, color=COL_REF, linewidth=1.3,
                 linestyle="--", label="PSIM (independente)")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(loc="best", fontsize=8.5, framealpha=0.95)

    axes[1].plot(fpga["t"], fpga["speed"], color=COL_FPGA, linewidth=1.8)
    axes[1].plot(psim["t"], psim["speed"], color=COL_REF, linewidth=1.35,
                 linestyle="--")
    axes[1].set_ylabel(r"$\omega_{mec}$ [rad/s]")

    axes[2].plot(fpga["t"], torque, color="black", linewidth=1.5,
                 drawstyle="steps-post")
    axes[2].set_ylabel(r"$T_L$ [N$\cdot$m]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].set_yticks([float(tload["pre"]), float(tload["post"])])

    for ax in axes:
        ax.axvline(step, color="black", linestyle=":", linewidth=1.0)
    axes[0].annotate("degrau de carga", xy=(step, axes[0].get_ylim()[1]),
                     xytext=(5, -5), textcoords="offset points", ha="left",
                     va="top", fontsize=8.5)
    axes[-1].set_xlim(start, end)
    fig.tight_layout(h_pad=0.35)
    name = f"HIL_L4B_{case['id']}_Evidence"
    eng.save_fig(fig, out_dir, name)
    return out_dir / f"{name}.pdf"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path,
                    default=eng.REPO_ROOT / "verification/results/2026-07-25_campaign_l4_final")
    ap.add_argument("--out", type=Path,
                    default=eng.REPO_ROOT / "docs/results-chapter/figures/publication")
    ap.add_argument("--case", action="append", choices=[c["id"] for c in l4b.CASES_L4B])
    args = ap.parse_args(argv)

    selected = [c for c in l4b.CASES_L4B if not args.case or c["id"] in args.case]
    for case in selected:
        if case["id"] in STARTUP_TACC_S:
            path = plot_startup(case, args.campaign, args.out)
        else:
            path = plot_load_step(case, args.campaign, args.out)
        print(f"[ok] {case['id']}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
