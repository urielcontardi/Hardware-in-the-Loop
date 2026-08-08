#!/usr/bin/env python3
"""Figuras L4 para publicação: FPGA real versus modelo C quando disponível."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import l2_figures as eng
import l4_figures as l4
import publication_figures as pub


CASES = {case["id"]: case for case in l4.CASES_L4}
COL_FPGA, COL_C = eng.COL_VHDL, eng.COL_C


def _style(axes):
    pub._style_axes(axes)
    for ax in np.atleast_1d(axes):
        ax.margins(x=0)


def _save(fig, out_dir: Path, name: str) -> Path:
    fig.tight_layout(h_pad=0.35)
    eng.save_fig(fig, out_dir, name)
    return out_dir / f"{name}.pdf"


def plot_fpga_startup(case_id: str, t_acc: float, campaign: Path, out_dir: Path) -> Path:
    """Rampa completa em hardware sem transformar a corrente em faixa opaca."""
    case = CASES[case_id]
    fpga = l4._load_full_fpga(case, campaign)
    stride = max(1, len(fpga["t"]) // 12000)
    fpga = {key: np.asarray(value)[::stride] for key, value in fpga.items()}
    end = t_acc + (0.30 if t_acc >= 5.0 else 0.25)
    mask = (fpga["t"] >= 0.0) & (fpga["t"] <= end)
    t = fpga["t"][mask]
    ia = eng.cc.inverse_clarke(fpga["ia"][mask], fpga["ib"][mask])[0]
    current_rms = pub.moving_rms(t, ia)
    flux = np.hypot(fpga["flux_a"][mask], fpga["flux_b"][mask])
    speed = fpga["speed"][mask]

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.2), sharex=True)
    _style(axes)
    axes[0].plot(t, current_rms, color=COL_FPGA, linewidth=1.7)
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[1].plot(t, flux, color=eng.PHASE_COLORS[2], linewidth=1.6)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, speed, color=COL_FPGA, linewidth=1.7)
    axes[2].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    for ax in axes:
        ax.axvline(t_acc, color="black", linestyle=":", linewidth=1.0)
    axes[0].annotate(r"fim da rampa $t_{acc}$", xy=(t_acc, axes[0].get_ylim()[1]),
                     xytext=(-5, -5), textcoords="offset points", ha="right",
                     va="top", fontsize=8.5)
    axes[-1].set_xlim(0.0, end)
    return _save(fig, out_dir, f"HIL_L4_{case_id}_StartupEvidence")


def _segment_channels(case_id: str, seg: str, campaign: Path):
    t_ms, data = l4.load_segment(CASES[case_id], seg, campaign)
    t = t_ms / 1000.0
    fpga_ia = np.asarray(eng.cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0])
    c_ia = np.asarray(eng.cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0])
    return t, data, fpga_ia, c_ia


def plot_a3_startup(campaign: Path, out_dir: Path) -> Path:
    t, data, fpga_ia, c_ia = _segment_channels("A3", "partida", campaign)
    fpga_flux = np.hypot(data["vhdl_flux_alpha"], data["vhdl_flux_beta"])
    c_flux = np.hypot(data["ref_flux_alpha"], data["ref_flux_beta"])
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.2), sharex=True)
    _style(axes)
    axes[0].plot(t, pub.moving_rms(t, fpga_ia), color=COL_FPGA, linewidth=1.7,
                 label="FPGA (real)")
    axes[0].plot(t, pub.moving_rms(t, c_ia), color=COL_C, linestyle="--",
                 linewidth=1.3, label="Modelo C")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, fpga_flux, color=COL_FPGA, linewidth=1.7)
    axes[1].plot(t, c_flux, color=COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, data["vhdl_speed"], color=COL_FPGA, linewidth=1.7)
    axes[2].plot(t, data["ref_speed"], color=COL_C, linestyle="--", linewidth=1.3)
    axes[2].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    return _save(fig, out_dir, "HIL_L4_A3_StartupEvidence")


def plot_a1_regime(campaign: Path, out_dir: Path) -> Path:
    t, data, fpga_ia, c_ia = _segment_channels("A1", "regime", campaign)
    keep = t >= float(t[-1]) - 0.10
    t, fpga_ia, c_ia = t[keep], fpga_ia[keep], c_ia[keep]
    residual = fpga_ia - c_ia
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.4), sharex=True)
    _style(axes)
    axes[0].plot(t, fpga_ia, color=COL_FPGA, linewidth=1.35, label="FPGA (real)")
    axes[0].plot(t, c_ia, color=COL_C, linestyle="--", linewidth=1.1, label="Modelo C")
    axes[0].set_ylabel(r"$i_a$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, residual, color=eng.COL_ERR_SPEED, linewidth=1.0)
    axes[1].axhline(0.0, color="0.35", linewidth=0.7)
    axes[1].set_ylabel(r"$\Delta i_a$ [A]")
    axes[1].set_xlabel("Tempo [s]")
    return _save(fig, out_dir, "HIL_L4_A1_RegimeEvidence")


def _concat_step(case_id: str, campaign: Path):
    parts = [_segment_channels(case_id, seg, campaign) for seg in ("partida", "regime")]
    t = np.concatenate([p[0] for p in parts])
    keys = parts[0][1].keys()
    data = {key: np.concatenate([np.asarray(p[1][key]) for p in parts]) for key in keys}
    fpga_ia = np.concatenate([p[2] for p in parts])
    c_ia = np.concatenate([p[3] for p in parts])
    order = np.argsort(t)
    return t[order], {key: value[order] for key, value in data.items()}, fpga_ia[order], c_ia[order]


def plot_b1_step(campaign: Path, out_dir: Path) -> Path:
    t, data, fpga_ia, c_ia = _concat_step("B1", campaign)
    start, step, end = 0.45, 0.60, 0.75
    keep = (t >= start) & (t <= end)
    t, fpga_ia, c_ia = t[keep], fpga_ia[keep], c_ia[keep]
    speed_fpga = np.asarray(data["vhdl_speed"])[keep]
    speed_c = np.asarray(data["ref_speed"])[keep]
    meta = json.loads((campaign / "B1_l4/l4_pwm_replay/capture/metrics.json").read_text())["tload"]
    torque = np.where(t < step, meta["pre"], meta["post"])
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.0), sharex=True)
    _style(axes)
    axes[0].plot(t, pub.moving_rms(t, fpga_ia), color=COL_FPGA, linewidth=1.7,
                 label="FPGA (real)")
    axes[0].plot(t, pub.moving_rms(t, c_ia), color=COL_C, linestyle="--",
                 linewidth=1.3, label="Modelo C")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, speed_fpga, color=COL_FPGA, linewidth=1.7)
    axes[1].plot(t, speed_c, color=COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].plot(t, torque, color="black", linewidth=1.5, drawstyle="steps-post")
    axes[2].set_ylabel(r"$T_L$ [N$\cdot$m]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].set_yticks([meta["pre"], meta["post"]])
    for ax in axes:
        ax.axvline(step, color="black", linestyle=":", linewidth=1.0)
    axes[-1].set_xlim(start, end)
    return _save(fig, out_dir, "HIL_L4_B1_StepEvidence")


def plot_b2_startup(campaign: Path, out_dir: Path) -> Path:
    t, data, fpga_ia, c_ia = _segment_channels("B2", "partida", campaign)
    keep = (t >= 0.10) & (t <= 0.60)
    t, fpga_ia, c_ia = t[keep], fpga_ia[keep], c_ia[keep]
    fpga_flux = np.hypot(data["vhdl_flux_alpha"], data["vhdl_flux_beta"])[keep]
    c_flux = np.hypot(data["ref_flux_alpha"], data["ref_flux_beta"])[keep]
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.2), sharex=True)
    _style(axes)
    axes[0].plot(t, pub.moving_rms(t, fpga_ia), color=COL_FPGA, linewidth=1.7,
                 label="FPGA (real)")
    axes[0].plot(t, pub.moving_rms(t, c_ia), color=COL_C, linestyle="--",
                 linewidth=1.3, label="Modelo C")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, fpga_flux, color=COL_FPGA, linewidth=1.7)
    axes[1].plot(t, c_flux, color=COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, np.asarray(data["vhdl_speed"])[keep], color=COL_FPGA, linewidth=1.7)
    axes[2].plot(t, np.asarray(data["ref_speed"])[keep], color=COL_C,
                 linestyle="--", linewidth=1.3)
    axes[2].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    axes[-1].set_xlim(0.10, 0.60)
    return _save(fig, out_dir, "HIL_L4_B2_StartupEvidence")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path,
                    default=eng.REPO_ROOT / "verification/results/2026-07-25_campaign_l4_final")
    ap.add_argument("--out", type=Path,
                    default=eng.REPO_ROOT / "docs/results-chapter/figures/publication")
    args = ap.parse_args(argv)
    jobs = [
        lambda: plot_fpga_startup("S0", 1.0, args.campaign, args.out),
        lambda: plot_fpga_startup("A5", 5.0, args.campaign, args.out),
        lambda: plot_a1_regime(args.campaign, args.out),
        lambda: plot_a3_startup(args.campaign, args.out),
        lambda: plot_b1_step(args.campaign, args.out),
        lambda: plot_b2_startup(args.campaign, args.out),
    ]
    for job in jobs:
        print(f"[ok] {job()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
