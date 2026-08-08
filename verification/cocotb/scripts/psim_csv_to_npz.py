#!/usr/bin/env python3
"""Merge a PSIM time-series export into an existing L4 npz (fpga_*/cmod_*),
adding psim_* arrays so the Results Explorer can overlay FPGA vs C model vs
PSIM on the same plot (see results_explorer_data.NPZ_OPTIONAL_PREFIX).

Input CSV is the raw PSIM SIMVIEW export, one row per solver step. May contain
extra columns (IuSim1/IvSim1/IwSim1/Wmec1/Te1 -- the C model DLL branch), but
this script only ever reads the PSIM-native motor branch:

    Time,Iu,Iv,Iw,motorSpeed[,...other columns ignored...]

This is intentional, not a default: the user wants the PSIM-native induction
motor block specifically (Iu/Iv/Iw/motorSpeed), not the C model running as a
DLL inside PSIM (IuSim1 etc.) -- those are a different thing (the same C code
already validated in L2/L3/L4) and were merged in by mistake in an earlier
pass of this script (silently switched to preferring the cmod branch when
present, without asking -- reverted). Do not reintroduce that preference
without confirming first.

Clarke transform matches the project convention (IM_Model.c:179-180,
im_reference_model.py:257): i_alpha = Iu, i_beta = (Iv - Iw) / sqrt(3).

Sign correction: PSIM's current probes measure the opposite polarity of the
FPGA/C-model convention. Confirmed empirically (not assumed) by
cross-correlating psim_ia/psim_ib against fpga_ia/fpga_ib on the S0 regime
window (native-motor branch): raw r=+0.59/+0.79, axis-swapped r=+0.06/-0.09
(ruled out), negated r=+0.95 with <0.1ms residual lag (i.e. same waveform,
opposite sign, no real time or axis mismatch). So ia/ib below are negated
relative to the raw CSV reading, on whichever branch is used. If a future
PSIM schematic revision flips the probe direction, this correction must be
removed or it will re-invert a signal that's already correct. Not yet
re-verified per-case that the C-model branch needs the identical sign flip
independently of the native-motor branch it was inferred from -- the r=0.9999
same-run check above is the basis for assuming it does.

Usage:
    python3 scripts/psim_csv_to_npz.py \\
        --psim-csv ../../extras/induction-motor-model/data/S0/S0_1us.csv \\
        --npz results/2026-07-25_l4_repeat/r1/S0_l4/l4_pwm_replay/capture/regime.npz \\
        --window 2.6534 3.1534
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


def load_psim_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"Time", "Iu", "Iv", "Iw", "motorSpeed"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path} missing columns: {sorted(missing)}")
    return df


def to_psim_channels(df: pd.DataFrame, t_start: float, t_end: float) -> tuple[dict[str, np.ndarray], str]:
    mask = (df["Time"] >= t_start) & (df["Time"] <= t_end)
    window = df.loc[mask]
    if window.empty:
        raise ValueError(
            f"No PSIM samples in [{t_start}, {t_end}] "
            f"(CSV covers [{df['Time'].min()}, {df['Time'].max()}])"
        )
    branch = "native motor (Iu/Iv/Iw/motorSpeed)"
    iu, iv, iw = window["Iu"], window["Iv"], window["Iw"]
    speed_rad_s = window["motorSpeed"].to_numpy() * (2.0 * math.pi / 60.0)

    # Negated: PSIM probe polarity is opposite the FPGA/C convention -- see
    # module docstring for the cross-correlation evidence behind this sign flip.
    ia = -iu.to_numpy()
    ib = -(iv.to_numpy() - iw.to_numpy()) / math.sqrt(3.0)
    channels = {
        "psim_t": window["Time"].to_numpy(),
        "psim_ia": ia,
        "psim_ib": ib,
        "psim_speed": speed_rad_s,
    }
    return channels, branch


def merge_into_npz(npz_path: Path, psim_channels: dict[str, np.ndarray]) -> None:
    with np.load(npz_path) as existing:
        merged = {key: existing[key] for key in existing.files}
    merged.update(psim_channels)
    np.savez(npz_path, **merged)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--psim-csv", required=True, type=Path, help="PSIM SIMVIEW export (Time,Iu,Iv,Iw,motorSpeed,...)")
    ap.add_argument("--npz", required=True, type=Path, help="Existing partida.npz/regime.npz to merge into (fpga_*/cmod_* preserved)")
    ap.add_argument("--window", nargs=2, type=float, metavar=("T_START", "T_END"),
                     help="Time window [s] to slice from the PSIM CSV. Default: match the npz's own fpga_t range.")
    args = ap.parse_args()

    if not args.npz.is_file():
        raise SystemExit(f"npz not found: {args.npz}")

    df = load_psim_csv(args.psim_csv)

    if args.window:
        t_start, t_end = args.window
    else:
        with np.load(args.npz) as existing:
            t_start, t_end = float(existing["fpga_t"].min()), float(existing["fpga_t"].max())
        t_end = min(t_end, float(df["Time"].max()))

    psim_channels, branch = to_psim_channels(df, t_start, t_end)
    merge_into_npz(args.npz, psim_channels)

    print(f"ok -> {args.npz}  (psim_t: {len(psim_channels['psim_t'])} samples, "
          f"[{psim_channels['psim_t'][0]:.4f}, {psim_channels['psim_t'][-1]:.4f}]s)")
    print(f"Nota: psim_ia/psim_ib/psim_speed vem do ramo {branch}, com sinal "
          "invertido (correcao de polaridade do probe, ver docstring). "
          "psim_flux_a/psim_flux_b nao disponiveis nesta exportacao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
