#!/usr/bin/env python3
"""Figuras L3 de publicação para os Grupos A e B."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import grupoab_figures as gab
import l2_figures as eng
import publication_figures as pub


def _cases():
    a = {row[0]: gab._case_a(*row) for row in gab._A}
    b = {row[0]: gab._case_b(*row) for row in gab._B}
    return a, b


def _load(case):
    t_ms, data = eng.load_case(case, gab.CAMP)
    t = t_ms / 1000.0
    top_ia = np.asarray(eng.cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0])
    ref_ia = np.asarray(eng.cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0])
    return t, data, top_ia, ref_ia


def _save(fig, out, name):
    fig.tight_layout(h_pad=0.35)
    eng.save_fig(fig, out, name)
    return out / f"{name}.pdf"


def plot_startup(case, t_acc: float, out: Path):
    t, data, top_ia, ref_ia = _load(case)
    end = min(float(t[-1]), t_acc + (0.25 if t_acc < 5 else 0.3))
    keep = t <= end
    t, top_ia, ref_ia = t[keep], top_ia[keep], ref_ia[keep]
    speed_top = np.asarray(data["vhdl_speed"])[keep]
    speed_ref = np.asarray(data["ref_speed"])[keep]
    error = speed_top - speed_ref
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.3), sharex=True)
    pub._style_axes(axes)
    axes[0].plot(t, pub.moving_rms(t, top_ia), color=eng.COL_VHDL, linewidth=1.7,
                 label="Top_HIL")
    axes[0].plot(t, pub.moving_rms(t, ref_ia), color=eng.COL_C, linestyle="--",
                 linewidth=1.3, label="C (replay)")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, speed_top, color=eng.COL_VHDL, linewidth=1.7)
    axes[1].plot(t, speed_ref, color=eng.COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].plot(t, error, color=eng.COL_ERR_SPEED, linewidth=1.1)
    axes[2].axhline(0.0, color="0.35", linewidth=0.7)
    axes[2].set_ylabel(r"$\Delta\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    for ax in axes:
        ax.axvline(t_acc, color="black", linestyle=":", linewidth=1.0)
    axes[-1].set_xlim(float(t[0]), end)
    return _save(fig, out, f"HIL_L3_GrupoA_{case['id']}_Evidence")


def plot_step(case, out: Path):
    t, data, top_ia, ref_ia = _load(case)
    pre, post, step = case["tload_step"]
    start, end = step - 0.15, step + 0.15
    keep = (t >= start) & (t <= end)
    t, top_ia, ref_ia = t[keep], top_ia[keep], ref_ia[keep]
    speed_top = np.asarray(data["vhdl_speed"])[keep]
    speed_ref = np.asarray(data["ref_speed"])[keep]
    torque = np.where(t < step, pre, post)
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.0), sharex=True)
    pub._style_axes(axes)
    axes[0].plot(t, pub.moving_rms(t, top_ia), color=eng.COL_VHDL, linewidth=1.7,
                 label="Top_HIL")
    axes[0].plot(t, pub.moving_rms(t, ref_ia), color=eng.COL_C, linestyle="--",
                 linewidth=1.3, label="C (replay)")
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, speed_top, color=eng.COL_VHDL, linewidth=1.7)
    axes[1].plot(t, speed_ref, color=eng.COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].plot(t, torque, color="black", linewidth=1.5, drawstyle="steps-post")
    axes[2].set_ylabel(r"$T_L$ [N$\cdot$m]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].set_yticks([pre, post])
    for ax in axes:
        ax.axvline(step, color="black", linestyle=":", linewidth=1.0)
    axes[-1].set_xlim(start, end)
    return _save(fig, out, f"HIL_L3_GrupoB_{case['id']}_Evidence")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=eng.REPO_ROOT / "docs/results-chapter/figures/publication")
    args = ap.parse_args(argv)
    a, b = _cases()
    for cid, t_acc in (("A1", 0.5), ("A5", 5.0)):
        print(f"[ok] {plot_startup(a[cid], t_acc, args.out)}")
    for cid in ("B1", "B2"):
        print(f"[ok] {plot_step(b[cid], args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
