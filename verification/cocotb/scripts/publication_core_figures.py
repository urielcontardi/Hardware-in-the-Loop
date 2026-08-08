#!/usr/bin/env python3
"""Figuras de evidência para os ensaios longos L2 e L3 do Capítulo 4."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import l2_figures as eng
import l3_figures
import publication_figures as pub


def _signals(case, campaign):
    t_ms, data = eng.load_case(case, campaign)
    t = np.asarray(t_ms) / 1000.0
    dut_ia = np.asarray(eng.cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0])
    ref_ia = np.asarray(eng.cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0])
    dut_flux = np.hypot(data["vhdl_flux_alpha"], data["vhdl_flux_beta"])
    ref_flux = np.hypot(data["ref_flux_alpha"], data["ref_flux_beta"])
    return t, data, dut_ia, ref_ia, dut_flux, ref_flux


def plot_evidence(case, campaign: Path, out: Path, name: str):
    t, data, dut_ia, ref_ia, dut_flux, ref_flux = _signals(case, campaign)
    labels = case.get("labels", {"dut": "VHDL", "ref": "C"})
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.2), sharex=True)
    pub._style_axes(axes)
    axes[0].plot(t, pub.moving_rms(t, dut_ia), color=eng.COL_VHDL, linewidth=1.7,
                 label=labels["dut"])
    axes[0].plot(t, pub.moving_rms(t, ref_ia), color=eng.COL_C, linestyle="--",
                 linewidth=1.3, label=labels["ref"])
    axes[0].set_ylabel(r"$I_{a,\mathrm{RMS}}$ [A]")
    axes[0].legend(fontsize=8.5)
    axes[1].plot(t, dut_flux, color=eng.COL_VHDL, linewidth=1.7)
    axes[1].plot(t, ref_flux, color=eng.COL_C, linestyle="--", linewidth=1.3)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, data["vhdl_speed"], color=eng.COL_VHDL, linewidth=1.7)
    axes[2].plot(t, data["ref_speed"], color=eng.COL_C, linestyle="--", linewidth=1.3)
    axes[2].set_ylabel(r"$\omega_{mec}$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    for ax in axes:
        ax.axvline(1.0, color="black", linestyle=":", linewidth=1.0)
    axes[-1].set_xlim(float(t[0]), float(t[-1]))
    fig.tight_layout(h_pad=0.35)
    eng.save_fig(fig, out, name)
    return out / f"{name}.pdf"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=eng.REPO_ROOT / "docs/results-chapter/figures/publication")
    args = ap.parse_args(argv)
    l2 = next(c for c in eng.CASES if c["id"] == "vf2s")
    replay = next(c for c in l3_figures.CASES_L3 if c["id"] == "pwmreplay_vf2s")
    full = next(c for c in l3_figures.CASES_L3 if c["id"] == "fullstack_vf2s")
    jobs = ((l2, eng.CAMPAIGN_DIR, "HIL_L2_VF2s_Evidence"),
            (replay, l3_figures.CAMPAIGN_DIR, "HIL_L3_PWMreplay_VF2s_Evidence"),
            (full, l3_figures.CAMPAIGN_DIR, "HIL_L3_Fullstack_VF2s_Evidence"))
    for case, campaign, name in jobs:
        print(f"[ok] {plot_evidence(case, campaign, args.out, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
