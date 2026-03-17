"""V/F motor startup report — C Reference Model vs VHDL TIM_Solver.

What this script does
---------------------
1. Runs the C reference model (IM_Model.c — MODEL_B2, floating-point) for a
   configurable motor-time duration using an open-loop V/F ramp.
2. Saves a decimated CSV with all motor variables.
3. Generates an interactive Plotly HTML report with 6 subplots:
     Row 1 — Phase currents  ia, ib, ic  [A]
     Row 2 — Stator currents iα, iβ      [A]
     Row 3 — Rotor flux      ψα, ψβ      [Wb]
     Row 4 — Speed           ωm, ωr      [rad/s]
     Row 5 — Torque          Te          [N·m]
     Row 6 — V/F excitation  Va, f_ref   [V / Hz]
4. Optionally overlays VHDL cocotb data (reports/vf_vhdl_vs_ref.csv).

Usage (from verification/cocotb/):
    uv run python scripts/vf_report.py                  # 2 s startup
    uv run python scripts/vf_report.py --duration 0.5   # faster preview
    uv run python scripts/vf_report.py --overlay        # add VHDL trace
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.vf_control import VFControl


# ---------------------------------------------------------------------------
# V/F parameters (matching PSIM setup)
# ---------------------------------------------------------------------------
F_NOMINAL_HZ     = 60.0
V_PEAK_NOMINAL   = 620.0   # Phase peak at f_nominal [V]  (760 Vrms L-L / √3 × √2)
ACC_RAMP_HZ_S    = 30.0    # 30 Hz/s → reaches 60 Hz in 2 s
TLOAD_NM         = 0.0

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
VHDL_CSV    = REPORTS_DIR / "vf_vhdl_vs_ref.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _downsample(rows: list[dict], max_points: int) -> list[dict]:
    n = len(rows)
    if n <= max_points:
        return rows
    step = n // max_points
    return rows[::step]


def _build_report(ref_rows: list[dict], vhdl_rows: list[dict] | None, out_path: Path) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("ERROR: plotly not installed.  Run: uv add plotly")
        sys.exit(1)

    overlay = bool(vhdl_rows)

    ref_rows = _downsample(ref_rows, 8000)
    t = [r["t_s"] for r in ref_rows]

    C_A  = "#00d4a8"   # teal   — α / a channel
    C_B  = "#4da8e8"   # blue   — β / b channel
    C_C  = "#a06ad8"   # purple — c channel
    C_VH = "#f0a030"   # amber  — VHDL overlay

    if overlay:
        ROWS = 7
        subplot_titles = [
            "Phase Currents  ia, ib, ic  [A]",
            "Stator Currents  iα, iβ  [A]",
            "Rotor Flux  ψα, ψβ  [Wb]",
            "Speed  ωm (mech)  [rad/s]",
            "Electromagnetic Torque  Te  [N·m]",
            "V/F Excitation — Phase Voltage Va [V] & f_ref [Hz]",
            "Error  (VHDL − C ref)  iα, iβ  [A]",
        ]
        ylabels = ["Current [A]", "Current [A]", "Flux [Wb]",
                   "Speed [rad/s]", "Torque [N·m]", "V / Hz", "Error [A]"]
    else:
        ROWS = 6
        subplot_titles = [
            "Phase Currents  ia, ib, ic  [A]",
            "Stator Currents  iα, iβ  [A]",
            "Rotor Flux  ψα, ψβ  [Wb]",
            "Speed  ωm (mech) · ωr (elec)  [rad/s]",
            "Electromagnetic Torque  Te  [N·m]",
            "V/F Excitation — Phase Voltage Va [V] & f_ref [Hz]",
        ]
        ylabels = ["Current [A]", "Current [A]", "Flux [Wb]",
                   "Speed [rad/s]", "Torque [N·m]", "V / Hz"]

    fig = make_subplots(
        rows=ROWS, cols=1,
        shared_xaxes=True,
        subplot_titles=subplot_titles,
        vertical_spacing=0.04 if overlay else 0.05,
    )

    def line(y, name, color, dash="solid", row=1):
        fig.add_trace(
            go.Scatter(x=t, y=y, name=name,
                       line=dict(color=color, width=1.4, dash=dash)),
            row=row, col=1,
        )

    # Row 1 — phase currents
    line([r["i_a"]  for r in ref_rows], "ref ia",  C_A,        row=1)
    line([r["i_b"]  for r in ref_rows], "ref ib",  C_B, "dot", row=1)
    line([r["i_c"]  for r in ref_rows], "ref ic",  C_C, "dash",row=1)

    # Row 2 — α-β currents
    line([r["i_alpha"] for r in ref_rows], "ref iα", C_A,        row=2)
    line([r["i_beta"]  for r in ref_rows], "ref iβ", C_B, "dot", row=2)

    # Row 3 — flux
    line([r["flux_alpha"] for r in ref_rows], "ref ψα", C_A,        row=3)
    line([r["flux_beta"]  for r in ref_rows], "ref ψβ", C_B, "dot", row=3)

    # Row 4 — speed
    line([r["speed_mech"] for r in ref_rows], "ref ωm", C_A, row=4)
    if not overlay:
        line([r["speed_elec"] for r in ref_rows], "ref ωr", C_B, "dot", row=4)

    # Row 5 — torque
    line([r["torque"] for r in ref_rows], "ref Te", C_A, row=5)

    # Row 6 — V/F
    line([r["va"]       for r in ref_rows], "Va [V]",     "#5a7898",       row=6)
    line([r["f_ref_hz"] for r in ref_rows], "f_ref [Hz]", "#a0c8f0", "dash", row=6)

    # VHDL overlay (dots, rows 2-4) + error row 7
    if overlay:
        vhdl_rows = _downsample(vhdl_rows, 2000)
        tv = [r["t_us"] * 1e-6 for r in vhdl_rows]

        def dots(y, name, row, symbol="circle"):
            fig.add_trace(
                go.Scatter(x=tv, y=y, name=name, mode="markers",
                           marker=dict(color=C_VH, size=5, symbol=symbol)),
                row=row, col=1,
            )

        dots([r["vhdl_i_alpha"]    for r in vhdl_rows], "vhdl iα",  row=2)
        dots([r["vhdl_i_beta"]     for r in vhdl_rows], "vhdl iβ",  row=2, symbol="x")
        dots([r["vhdl_flux_alpha"] for r in vhdl_rows], "vhdl ψα",  row=3)
        dots([r["vhdl_flux_beta"]  for r in vhdl_rows], "vhdl ψβ",  row=3, symbol="x")
        dots([r["vhdl_speed"]      for r in vhdl_rows], "vhdl ωm",  row=4)

        # Row 7 — error (VHDL − ref)
        err_alpha = [r["vhdl_i_alpha"] - r["ref_i_alpha"] for r in vhdl_rows]
        err_beta  = [r["vhdl_i_beta"]  - r["ref_i_beta"]  for r in vhdl_rows]
        fig.add_trace(
            go.Scatter(x=tv, y=err_alpha, name="err iα", mode="lines",
                       line=dict(color=C_A, width=1.2)),
            row=7, col=1,
        )
        fig.add_trace(
            go.Scatter(x=tv, y=err_beta, name="err iβ", mode="lines",
                       line=dict(color=C_B, width=1.2, dash="dot")),
            row=7, col=1,
        )
        # Zero reference line
        fig.add_trace(
            go.Scatter(x=[tv[0], tv[-1]], y=[0, 0], name="zero",
                       mode="lines", line=dict(color="#ffffff", width=0.8, dash="dash"),
                       showlegend=False),
            row=7, col=1,
        )

        # Print stats
        mae_alpha = sum(abs(e) for e in err_alpha) / len(err_alpha)
        mae_beta  = sum(abs(e) for e in err_beta)  / len(err_beta)
        max_alpha = max(abs(e) for e in err_alpha)
        max_beta  = max(abs(e) for e in err_beta)
        print("Overlay error stats:")
        print(f"  iα — MAE={mae_alpha:.4e} A   max={max_alpha:.4e} A")
        print(f"  iβ — MAE={mae_beta:.4e} A   max={max_beta:.4e} A")

    # Layout
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#070c16",
        plot_bgcolor="#050b14",
        font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
        title=dict(
            text=(
                "TIM Solver — V/F Motor Startup  │  "
                "C Reference Model (MODEL_B2, floating-point)"
                + ("  +  VHDL TIM_Solver overlay" if overlay else "")
            ),
            font=dict(size=14),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=10)),
        height=1400 if overlay else 1200,
    )

    for row in range(1, ROWS + 1):
        fig.update_xaxes(gridcolor="#162233", row=row, col=1)
        fig.update_yaxes(gridcolor="#162233", row=row, col=1)

    fig.update_xaxes(title_text="Time [s]", row=ROWS, col=1)
    for i, lbl in enumerate(ylabels, 1):
        fig.update_yaxes(title_text=lbl, row=i, col=1)

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"Report saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate V/F motor startup report")
    parser.add_argument("--duration",  type=float, default=2.0,
                        help="Motor simulation duration [s] (default: 2.0)")
    parser.add_argument("--acc-ramp",  type=float, default=ACC_RAMP_HZ_S,
                        help=f"Frequency ramp [Hz/s] (default: {ACC_RAMP_HZ_S})")
    parser.add_argument("--tload",     type=float, default=TLOAD_NM,
                        help="Load torque [N·m] (default: 0)")
    parser.add_argument("--overlay",   action="store_true",
                        help="Overlay VHDL CSV if present in reports/")
    parser.add_argument("--no-html",   action="store_true",
                        help="Skip HTML generation (CSV only)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # When --overlay is requested, read the VHDL CSV first to determine its
    # time window and run the C model for exactly the same duration.
    vhdl_rows_preload = None
    if args.overlay and VHDL_CSV.exists():
        with VHDL_CSV.open() as f:
            raw = list(csv.DictReader(f))
        float_keys = [k for k in raw[0] if k != "step"]
        for r in raw:
            for k in float_keys:
                r[k] = float(r[k])
        vhdl_rows_preload = raw
        vhdl_duration = max(r["t_us"] for r in vhdl_rows_preload) * 1e-6
        print(f"VHDL CSV loaded: {VHDL_CSV} ({len(vhdl_rows_preload)} rows, "
              f"duration={vhdl_duration*1e6:.1f} µs)")
        args.duration = vhdl_duration
    elif args.overlay:
        print(f"VHDL CSV not found at {VHDL_CSV} — running full duration.")

    params = IMPhysicalParams.defaults()
    ref = InductionMotorReferenceModel(params=params, backend="auto")
    vf  = VFControl(
        f_nominal=F_NOMINAL_HZ,
        v_peak_nominal=V_PEAK_NOMINAL,
        acc_ramp_hz_s=args.acc_ramp,
        ts=params.ts,
        tload=args.tload,
    )

    total_steps = int(args.duration / params.ts)
    decimate    = max(1, total_steps // 50_000)
    print(f"Running C reference model: {total_steps:,} steps "
          f"({args.duration*1e6:.1f} µs motor time, 1 point per {decimate} steps) ..."
          if args.duration < 0.01 else
          f"Running C reference model: {total_steps:,} steps "
          f"({args.duration:.3f} s motor time, 1 point per {decimate} steps) ...")

    ref_csv = REPORTS_DIR / "vf_ref_model.csv"
    ref_rows: list[dict] = []

    fieldnames = [
        "t_s", "va", "vb", "vc", "f_ref_hz",
        "i_a", "i_b", "i_c",
        "i_alpha", "i_beta",
        "flux_alpha", "flux_beta",
        "speed_mech", "speed_elec",
        "torque",
    ]

    with ref_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for step in range(total_steps):
            va, vb, vc = vf.step()
            s = ref.step(va, vb, vc, vf.tload)

            if step % decimate == 0:
                row = {
                    "t_s":        step * params.ts,
                    "va": va, "vb": vb, "vc": vc,
                    "f_ref_hz":   vf.f_ref,
                    "i_a":        s.i_a,
                    "i_b":        s.i_b,
                    "i_c":        s.i_c,
                    "i_alpha":    s.i_alpha,
                    "i_beta":     s.i_beta,
                    "flux_alpha": s.flux_alpha,
                    "flux_beta":  s.flux_beta,
                    "speed_mech": s.speed_mech,
                    "speed_elec": s.speed_elec,
                    "torque":     s.torque,
                }
                writer.writerow(row)
                ref_rows.append(row)

            if step % (total_steps // 10) == 0:
                pct = 100 * step // total_steps
                print(f"  {pct:3d}%  t={step*params.ts:.3f}s  "
                      f"f={vf.f_ref:.1f} Hz  "
                      f"ωm={s.speed_mech:.1f} rad/s  "
                      f"Te={s.torque:.2f} N·m  "
                      f"ia={s.i_a:.3f} A")

    print(f"Reference CSV: {ref_csv} ({len(ref_rows)} rows)")

    if args.no_html:
        return

    # Use preloaded VHDL rows (already parsed at duration-override stage above)
    vhdl_rows = vhdl_rows_preload

    _build_report(ref_rows, vhdl_rows, REPORTS_DIR / "vf_report.html")


if __name__ == "__main__":
    main()
