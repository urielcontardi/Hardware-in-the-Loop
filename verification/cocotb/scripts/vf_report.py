"""Standalone V/F motor startup report.

Runs the C reference model for a configurable motor-time duration with an
open-loop V/F ramp, generates a CSV, then produces an interactive HTML
report (Plotly).  Optionally overlays VHDL cocotb data from a previously
generated CSV.

Usage (from verification/cocotb/):
    uv run python scripts/vf_report.py              # full 2-second startup
    uv run python scripts/vf_report.py --duration 0.5
    uv run python scripts/vf_report.py --overlay     # include VHDL CSV if present
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Make sure project models are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.vf_control import VFControl


# ---------------------------------------------------------------------------
# Default V/F parameters (matching PSIM setup)
# ---------------------------------------------------------------------------
F_NOMINAL_HZ = 60.0
V_PEAK_NOMINAL = 620.0    # Phase peak at f_nominal [V]
ACC_RAMP_HZ_S = 30.0      # 30 Hz/s → reaches 60 Hz in 2 s
TLOAD_NM = 0.0

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
VHDL_CSV = REPORTS_DIR / "vf_vhdl_vs_ref.csv"


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------
def _downsample(rows: list[dict], max_points: int) -> list[dict]:
    """Keep at most max_points rows, evenly spaced."""
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

    ref_rows = _downsample(ref_rows, 5000)

    t_ref = [r["t_s"] for r in ref_rows]

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        subplot_titles=[
            "Stator Currents (α–β)",
            "Rotor Flux (α–β)",
            "Mechanical Speed",
            "V/F — Phase Voltage & Frequency",
        ],
        vertical_spacing=0.08,
    )

    # Palette
    COLOR_REF_A = "#00d4a8"
    COLOR_REF_B = "#4da8e8"
    COLOR_VH_A  = "#f0a030"
    COLOR_VH_B  = "#e83050"

    # Row 1 — currents
    fig.add_trace(go.Scatter(x=t_ref, y=[r["i_alpha"] for r in ref_rows],
                             name="ref iα", line=dict(color=COLOR_REF_A, width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=t_ref, y=[r["i_beta"] for r in ref_rows],
                             name="ref iβ", line=dict(color=COLOR_REF_B, width=1.5, dash="dot")), row=1, col=1)

    # Row 2 — flux
    fig.add_trace(go.Scatter(x=t_ref, y=[r["flux_alpha"] for r in ref_rows],
                             name="ref ψα", line=dict(color=COLOR_REF_A, width=1.5)), row=2, col=1)
    fig.add_trace(go.Scatter(x=t_ref, y=[r["flux_beta"] for r in ref_rows],
                             name="ref ψβ", line=dict(color=COLOR_REF_B, width=1.5, dash="dot")), row=2, col=1)

    # Row 3 — speed
    fig.add_trace(go.Scatter(x=t_ref, y=[r["speed_mech"] for r in ref_rows],
                             name="ref ωm", line=dict(color=COLOR_REF_A, width=1.5)), row=3, col=1)

    # Row 4 — V/F
    fig.add_trace(go.Scatter(x=t_ref, y=[r["va"] for r in ref_rows],
                             name="Va", line=dict(color="#5a7898", width=1)), row=4, col=1)
    fig.add_trace(go.Scatter(x=t_ref, y=[r["f_ref_hz"] for r in ref_rows],
                             name="f_ref [Hz]", line=dict(color="#a0c8f0", width=1.5, dash="dash"),
                             yaxis="y8"), row=4, col=1)

    # Overlay VHDL if present
    if vhdl_rows:
        vhdl_rows = _downsample(vhdl_rows, 2000)
        t_vh = [r["t_us"] * 1e-6 for r in vhdl_rows]

        fig.add_trace(go.Scatter(x=t_vh, y=[r["vhdl_i_alpha"] for r in vhdl_rows],
                                 name="vhdl iα", mode="markers",
                                 marker=dict(color=COLOR_VH_A, size=4)), row=1, col=1)
        fig.add_trace(go.Scatter(x=t_vh, y=[r["vhdl_i_beta"] for r in vhdl_rows],
                                 name="vhdl iβ", mode="markers",
                                 marker=dict(color=COLOR_VH_B, size=4, symbol="x")), row=1, col=1)
        fig.add_trace(go.Scatter(x=t_vh, y=[r["vhdl_flux_alpha"] for r in vhdl_rows],
                                 name="vhdl ψα", mode="markers",
                                 marker=dict(color=COLOR_VH_A, size=4)), row=2, col=1)
        fig.add_trace(go.Scatter(x=t_vh, y=[r["vhdl_speed"] for r in vhdl_rows],
                                 name="vhdl ωm", mode="markers",
                                 marker=dict(color=COLOR_VH_A, size=4)), row=3, col=1)

    # Layout
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#070c16",
        plot_bgcolor="#050b14",
        font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
        title=dict(
            text="TIM Solver — V/F Motor Startup: C Reference vs VHDL",
            font=dict(size=15),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        height=900,
    )
    fig.update_xaxes(title_text="Time [s]", row=4, col=1, gridcolor="#162233")
    for row in range(1, 5):
        fig.update_xaxes(gridcolor="#162233", row=row, col=1)
        fig.update_yaxes(gridcolor="#162233", row=row, col=1)
    fig.update_yaxes(title_text="Current [A]", row=1, col=1)
    fig.update_yaxes(title_text="Flux [Wb]", row=2, col=1)
    fig.update_yaxes(title_text="ωm [rad/s]", row=3, col=1)
    fig.update_yaxes(title_text="Voltage [V]", row=4, col=1)

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"Report saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate V/F motor startup report")
    parser.add_argument("--duration", type=float, default=2.0,
                        help="Motor simulation duration [s] (default: 2.0)")
    parser.add_argument("--acc-ramp", type=float, default=ACC_RAMP_HZ_S,
                        help=f"Frequency ramp [Hz/s] (default: {ACC_RAMP_HZ_S})")
    parser.add_argument("--tload", type=float, default=TLOAD_NM,
                        help="Load torque [N·m] (default: 0)")
    parser.add_argument("--overlay", action="store_true",
                        help="Overlay VHDL CSV if present in reports/")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip HTML generation (CSV only)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    params = IMPhysicalParams.defaults()
    ref = InductionMotorReferenceModel(params=params, backend="auto")
    vf = VFControl(
        f_nominal=F_NOMINAL_HZ,
        v_peak_nominal=V_PEAK_NOMINAL,
        acc_ramp_hz_s=args.acc_ramp,
        ts=params.ts,
        tload=args.tload,
    )

    total_steps = int(args.duration / params.ts)
    print(f"Running C reference model: {total_steps:,} steps ({args.duration:.1f}s motor time) ...")

    ref_csv_path = REPORTS_DIR / "vf_ref_model.csv"
    ref_rows: list[dict] = []

    # Decimation: keep at most 50k rows in CSV to avoid huge files
    decimate = max(1, total_steps // 50_000)

    with ref_csv_path.open("w", newline="") as f:
        fieldnames = ["t_s", "va", "vb", "vc", "f_ref_hz",
                      "i_alpha", "i_beta", "flux_alpha", "flux_beta", "speed_mech"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for step in range(total_steps):
            va, vb, vc = vf.step()
            state = ref.step(va, vb, vc, vf.tload)

            if step % decimate == 0:
                row = {
                    "t_s": step * params.ts,
                    "va": va,
                    "vb": vb,
                    "vc": vc,
                    "f_ref_hz": vf.f_ref,
                    "i_alpha": state.i_alpha,
                    "i_beta": state.i_beta,
                    "flux_alpha": state.flux_alpha,
                    "flux_beta": state.flux_beta,
                    "speed_mech": state.speed_mech,
                }
                writer.writerow(row)
                ref_rows.append(row)

            if step % (total_steps // 10) == 0:
                pct = 100 * step // total_steps
                print(f"  {pct}%  t={step*params.ts:.3f}s  f={vf.f_ref:.1f}Hz  "
                      f"speed={state.speed_mech:.2f} rad/s")

    print(f"Reference CSV saved: {ref_csv_path} ({len(ref_rows)} rows)")

    if args.no_html:
        return

    # Load VHDL CSV if requested and available
    vhdl_rows = None
    if args.overlay and VHDL_CSV.exists():
        with VHDL_CSV.open() as f:
            vhdl_rows = list(csv.DictReader(f))
        # Convert strings to float
        float_keys = [k for k in vhdl_rows[0] if k != "step"]
        for r in vhdl_rows:
            for k in float_keys:
                r[k] = float(r[k])
        print(f"VHDL CSV loaded: {VHDL_CSV} ({len(vhdl_rows)} rows)")
    elif args.overlay:
        print(f"VHDL CSV not found ({VHDL_CSV}), skipping overlay.")

    html_path = REPORTS_DIR / "vf_report.html"
    _build_report(ref_rows, vhdl_rows, html_path)


if __name__ == "__main__":
    main()
