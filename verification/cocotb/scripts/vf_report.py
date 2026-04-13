"""Motor startup report — C Reference Model vs VHDL TIM_Solver.

Layout (overlay mode — two independent sections):

  ┌─────────────────────────────────────────────────────────────┐
  │  SECTION A — C Reference Model  (full --duration run)       │
  │  Shows complete motor behavior: sinusoidal waveforms,       │
  │  flux build-up, speed ramp.  Time axis in seconds.         │
  │                                                             │
  │   Row 1: Applied voltages  vα, vβ  [V]                     │
  │   Row 2: Stator currents   iα, iβ  [A]                     │
  │   Row 3: Rotor flux        ψα, ψβ  [Wb]                    │
  │   Row 4: Speed             ωm      [rad/s]                  │
  ├─────────────────────────────────────────────────────────────┤
  │  SECTION B — VHDL vs C comparison  (VHDL CSV window)        │
  │  Validates VHDL fixed-point math against floating-point C.  │
  │  Time axis in µs.  C = solid, VHDL = dashed.               │
  │                                                             │
  │   Row 5: Applied voltages  vα, vβ  [V]  (zoom view)        │
  │   Row 6: iα  — C ref (teal) vs VHDL (orange)              │
  │   Row 7: iβ  — C ref (blue) vs VHDL (amber)               │
  │   Row 8: ψα, ψβ — C ref vs VHDL                           │
  │   Row 9: ωm    — C ref vs VHDL                             │
  │   Row 10: Error (VHDL − C): iα, iβ                         │
  └─────────────────────────────────────────────────────────────┘

Usage (from verification/cocotb/):
    # V/F ramp — C model for 2 s, overlay VHDL 300 µs window
    uv run python scripts/vf_report.py --overlay

    # Pure sine — C model for 200 ms (shows ~12 cycles), overlay VHDL
    uv run python scripts/vf_report.py --sine --duration 0.2 --overlay \\
        --vhdl-csv reports/sine_vhdl_vs_ref.csv

    # C model only (no VHDL overlay)
    uv run python scripts/vf_report.py --duration 2.0
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.vf_control import VFControl
from models.sine_control import SineControl


# ---------------------------------------------------------------------------
# Default V/F parameters (matching PSIM setup)
# ---------------------------------------------------------------------------
F_NOMINAL_HZ    = 60.0
V_PEAK_NOMINAL  = 620.0   # Phase peak at f_nominal [V]
ACC_RAMP_HZ_S   = 60.0    # 60 Hz/s → reaches 60 Hz in 1 s
TLOAD_NM        = 0.0

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


# ---------------------------------------------------------------------------
# Clarke helpers
# ---------------------------------------------------------------------------
def _clarke_alpha(va: float, vb: float, vc: float) -> float:
    """Amplitude-invariant Clarke — alpha axis."""
    return (2.0 * va - vb - vc) / 3.0


def _clarke_beta(va: float, vb: float, vc: float) -> float:
    """Amplitude-invariant Clarke — beta axis."""
    return (vb - vc) / math.sqrt(3.0)


# ---------------------------------------------------------------------------
# Downsampler
# ---------------------------------------------------------------------------
def _rpm(rad_s: float) -> float:
    """Convert angular velocity from rad/s to RPM."""
    return rad_s * 60.0 / (2.0 * math.pi)


def _downsample(rows: list[dict], max_points: int) -> list[dict]:
    n = len(rows)
    if n <= max_points:
        return rows
    step = n // max_points
    return rows[::step]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------
def _build_report(
    ref_rows: list[dict],
    vhdl_rows: list[dict] | None,
    out_path: Path,
    title_suffix: str = "",
) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("ERROR: plotly not installed.  Run: uv add plotly")
        sys.exit(1)

    overlay = bool(vhdl_rows)

    # ── Colour palette ──────────────────────────────────────────────────────
    # C reference  → cool tones (teal / blue)
    # VHDL DUT     → warm tones (orange / amber)
    C_REF_A = "#00d4a8"   # teal   — C ref, α axis
    C_REF_B = "#4da8e8"   # blue   — C ref, β axis
    C_VH_A  = "#f07030"   # orange — VHDL, α axis
    C_VH_B  = "#f0c040"   # amber  — VHDL, β axis
    C_ERR_A = "#ff6b6b"   # red    — error iα
    C_ERR_B = "#ffa07a"   # salmon — error iβ

    def _trace(fig, x, y, name, color, dash="solid", width=1.6, row=1, col=1):
        fig.add_trace(
            go.Scatter(x=x, y=y, name=name,
                       line=dict(color=color, width=width, dash=dash)),
            row=row, col=col,
        )

    # ── Non-overlay: single column, C model only ────────────────────────────
    if not overlay:
        ref_rows = _downsample(ref_rows, 8000)
        t = [r["t_s"] for r in ref_rows]

        titles = [
            "① Applied Voltages  vα, vβ  [V]",
            "② Stator Currents  iα, iβ  [A]",
            "③ Rotor Flux  ψα, ψβ  [Wb]",
            "④ Speed  ωm (mechanical) · ωr (electrical)  [RPM]",
            "⑤ Electromagnetic Torque  Te  [N·m]",
        ]
        ylabels = ["Voltage [V]", "Current [A]", "Flux [Wb]", "Speed [RPM]", "Torque [N·m]"]

        fig = make_subplots(rows=5, cols=1, shared_xaxes=True,
                            subplot_titles=titles, vertical_spacing=0.06)

        va_a = [_clarke_alpha(r["va"], r["vb"], r["vc"]) for r in ref_rows]
        va_b = [_clarke_beta (r["va"], r["vb"], r["vc"]) for r in ref_rows]
        _trace(fig, t, va_a,                                    "vα",    C_REF_A, row=1)
        _trace(fig, t, va_b,                                    "vβ",    C_REF_B, "dash", row=1)
        _trace(fig, t, [r["i_alpha"]    for r in ref_rows],     "iα",    C_REF_A, row=2)
        _trace(fig, t, [r["i_beta"]     for r in ref_rows],     "iβ",    C_REF_B, "dash", row=2)
        _trace(fig, t, [r["flux_alpha"] for r in ref_rows],     "ψα",    C_REF_A, row=3)
        _trace(fig, t, [r["flux_beta"]  for r in ref_rows],     "ψβ",    C_REF_B, "dash", row=3)
        _trace(fig, t, [_rpm(r["speed_mech"]) for r in ref_rows], "ωm",  C_REF_A,         row=4)
        _trace(fig, t, [_rpm(r["speed_elec"]) for r in ref_rows], "ωr", C_REF_B, "dash", row=4)
        _trace(fig, t, [r["torque"]     for r in ref_rows],     "Te",    C_REF_A, row=5)

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#070c16", plot_bgcolor="#050b14",
            font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
            title=dict(text=f"TIM Solver — Motor Startup  │  C Reference Model{title_suffix}",
                       font=dict(size=13), x=0.5, xanchor="center"),
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.01,
                        font=dict(size=10), bgcolor="rgba(10,20,40,0.8)",
                        bordercolor="#2a3f55", borderwidth=1),
            height=220 * 5 + 80,
            margin=dict(r=160),
        )
        for row in range(1, 6):
            fig.update_xaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)
            fig.update_yaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)
        fig.update_xaxes(title_text="Time [s]", row=5, col=1)
        for i, lbl in enumerate(ylabels, 1):
            fig.update_yaxes(title_text=lbl, row=i, col=1)

        fig.write_html(str(out_path), include_plotlyjs="cdn")
        print(f"Report saved: {out_path}")
        return

    # ── Overlay: 2-column layout ─────────────────────────────────────────────
    #
    # Col 1 (left):  C model full duration — sinusoids visible [time: seconds]
    # Col 2 (right): VHDL vs C 300µs zoom                    [time: µs]
    # 5 rows: voltages | currents iα | currents iβ | flux | speed+error
    #
    vhdl_rows = _downsample(vhdl_rows, 3000)
    ref_rows  = _downsample(ref_rows,  8000)

    t_ref_s  = [r["t_s"]  for r in ref_rows]
    t_vhd_us = [r["t_us"] for r in vhdl_rows]

    # C model rows clipped to the VHDL window (right column reference)
    vhdl_t_max_us = max(t_vhd_us)
    ref_zoom = [r for r in ref_rows if r["t_s"] * 1e6 <= vhdl_t_max_us * 1.05] or ref_rows[:100]
    t_ref_zoom_us = [r["t_s"] * 1e6 for r in ref_zoom]

    ROWS = 5
    col_titles = [
        f"C Reference Model — full run{title_suffix}  [time: s]",
        f"VHDL Q14.28 vs C ref — {vhdl_t_max_us:.0f} µs zoom  [time: µs]",
    ]
    row_titles = ["vα, vβ [V]", "iα [A]", "iβ [A]", "ψα, ψβ [Wb]", "ωm/ωr [RPM] + error"]

    fig = make_subplots(
        rows=ROWS, cols=2,
        shared_xaxes="columns",   # link rows within each column independently
        shared_yaxes=False,
        column_titles=col_titles,
        row_titles=row_titles,
        vertical_spacing=0.06,
        horizontal_spacing=0.10,
        row_heights=[0.16, 0.21, 0.21, 0.21, 0.21],
    )

    # Helper: suppress duplicate legend entries with legendgroup.
    # Deduplication key is (legendgroup, name) so the same signal name can appear
    # in two different groups (C Reference vs VHDL DUT) without being suppressed.
    _shown: set[str] = set()        # tracks "group::name" pairs already in legend
    _group_titled: set[str] = set() # tracks which groups already have a title

    def _t(fig, x, y, name, color, dash="solid", width=1.6, row=1, col=1,
           group=None, gtitle=None):
        lg = group or name
        key = f"{lg}::{name}"
        show = key not in _shown
        if show:
            _shown.add(key)
        kw: dict = {}
        if gtitle and lg not in _group_titled:
            kw["legendgrouptitle_text"] = gtitle
            kw["legendgrouptitle"] = dict(
                text=gtitle, font=dict(size=10, color="#8ba8c8", family="IBM Plex Mono, monospace")
            )
            _group_titled.add(lg)
        fig.add_trace(
            go.Scatter(
                x=x, y=y, name=name,
                legendgroup=lg,
                showlegend=show,
                line=dict(color=color, width=width, dash=dash),
                **kw,
            ),
            row=row, col=col,
        )

    # ── Column 1: C model overview ───────────────────────────────────────────
    va_a = [_clarke_alpha(r["va"], r["vb"], r["vc"]) for r in ref_rows]
    va_b = [_clarke_beta (r["va"], r["vb"], r["vc"]) for r in ref_rows]

    _t(fig, t_ref_s, va_a,                                 "vα",        C_REF_A,         row=1, col=1, group="Input Voltages", gtitle="Input Voltages")
    _t(fig, t_ref_s, va_b,                                 "vβ",        C_REF_B, "dash", row=1, col=1, group="Input Voltages")
    _t(fig, t_ref_s, [r["i_alpha"]    for r in ref_rows],  "iα",  C_REF_A,         row=2, col=1, group="C Reference", gtitle="C Reference Model")
    _t(fig, t_ref_s, [r["i_beta"]     for r in ref_rows],  "iβ",  C_REF_B, "dash", row=3, col=1, group="C Reference")
    _t(fig, t_ref_s, [r["flux_alpha"] for r in ref_rows],  "ψα",  C_REF_A,         row=4, col=1, group="C Reference")
    _t(fig, t_ref_s, [r["flux_beta"]  for r in ref_rows],  "ψβ",  C_REF_B, "dash", row=4, col=1, group="C Reference")
    _t(fig, t_ref_s, [_rpm(r["speed_mech"]) for r in ref_rows], "ωm", C_REF_A,         row=5, col=1, group="C Reference")
    _t(fig, t_ref_s, [_rpm(r["speed_elec"]) for r in ref_rows], "ωr", C_REF_B, "dash", row=5, col=1, group="C Reference")

    # VHDL validation window shading on col 1
    vhdl_t_max_s = vhdl_t_max_us * 1e-6
    for row in range(1, ROWS + 1):
        fig.add_vrect(
            x0=0, x1=vhdl_t_max_s,
            fillcolor="rgba(100,180,255,0.06)",
            line=dict(color="rgba(100,180,255,0.35)", width=1, dash="dot"),
            row=row, col=1,
        )

    # ── Column 2: VHDL vs C zoom ─────────────────────────────────────────────
    vz_a = [_clarke_alpha(r["va"], r["vb"], r["vc"]) for r in vhdl_rows]
    vz_b = [_clarke_beta (r["va"], r["vb"], r["vc"]) for r in vhdl_rows]

    # Row 1: voltages (deduplicated into "Input Voltages" group from col 1)
    _t(fig, t_vhd_us, vz_a,                                       "vα",  C_REF_A,         row=1, col=2, group="Input Voltages")
    _t(fig, t_vhd_us, vz_b,                                       "vβ",  C_REF_B, "dash", row=1, col=2, group="Input Voltages")

    # Row 2: iα — C ref vs VHDL
    _t(fig, t_ref_zoom_us, [r["i_alpha"]      for r in ref_zoom],  "iα",  C_REF_A,        row=2, col=2, group="C Reference")
    _t(fig, t_vhd_us,      [r["vhdl_i_alpha"] for r in vhdl_rows], "iα",  C_VH_A, "dash", row=2, col=2, group="VHDL DUT", gtitle="VHDL Q14.28 DUT")

    # Row 3: iβ — C ref vs VHDL
    _t(fig, t_ref_zoom_us, [r["i_beta"]       for r in ref_zoom],  "iβ",  C_REF_B,        row=3, col=2, group="C Reference")
    _t(fig, t_vhd_us,      [r["vhdl_i_beta"]  for r in vhdl_rows], "iβ",  C_VH_B, "dash", row=3, col=2, group="VHDL DUT")

    # Row 4: flux
    _t(fig, t_ref_zoom_us, [r["flux_alpha"]      for r in ref_zoom],  "ψα", C_REF_A,        row=4, col=2, group="C Reference")
    _t(fig, t_vhd_us,      [r["vhdl_flux_alpha"] for r in vhdl_rows], "ψα", C_VH_A, "dash", row=4, col=2, group="VHDL DUT")
    _t(fig, t_ref_zoom_us, [r["flux_beta"]       for r in ref_zoom],  "ψβ", C_REF_B,        row=4, col=2, group="C Reference")
    _t(fig, t_vhd_us,      [r["vhdl_flux_beta"]  for r in vhdl_rows], "ψβ", C_VH_B, "dash", row=4, col=2, group="VHDL DUT")

    # Row 5: speed + error (shared panel) — RPM
    _t(fig, t_ref_zoom_us, [_rpm(r["speed_mech"]) for r in ref_zoom],   "ωm", C_REF_A,        row=5, col=2, group="C Reference")
    _t(fig, t_vhd_us,      [_rpm(r["vhdl_speed"])  for r in vhdl_rows], "ωm", C_VH_A, "dash", row=5, col=2, group="VHDL DUT")

    err_alpha = [r["vhdl_i_alpha"] - r["ref_i_alpha"] for r in vhdl_rows]
    err_beta  = [r["vhdl_i_beta"]  - r["ref_i_beta"]  for r in vhdl_rows]
    mae_alpha = sum(abs(e) for e in err_alpha) / len(err_alpha)
    mae_beta  = sum(abs(e) for e in err_beta)  / len(err_beta)
    max_alpha = max(abs(e) for e in err_alpha)
    max_beta  = max(abs(e) for e in err_beta)
    print(f"Overlay error stats (VHDL − C ref):")
    print(f"  iα — MAE={mae_alpha:.4e} A   max={max_alpha:.4e} A")
    print(f"  iβ — MAE={mae_beta:.4e} A   max={max_beta:.4e} A")

    # Error traces on row 5 col 2
    _t(fig, t_vhd_us, err_alpha, f"err iα  MAE={mae_alpha:.1e} A", C_ERR_A,        width=1.2, row=5, col=2, group="Error (VHDL − C ref)", gtitle="Error (VHDL − C ref)")
    _t(fig, t_vhd_us, err_beta,  f"err iβ  MAE={mae_beta:.1e} A",  C_ERR_B, "dot", width=1.2, row=5, col=2, group="Error (VHDL − C ref)")
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.25)", width=0.7, dash="dot"),
                  row=5, col=2)

    # ── X-axis labels (bottom row only) ──────────────────────────────────────
    fig.update_xaxes(title_text="Time [s]",  row=ROWS, col=1)
    fig.update_xaxes(title_text="Time [µs]", row=ROWS, col=2)

    # ── Grid styling ─────────────────────────────────────────────────────────
    for r in range(1, ROWS + 1):
        for c in (1, 2):
            fig.update_xaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=r, col=c)
            fig.update_yaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=r, col=c)

    # ── Global layout ────────────────────────────────────────────────────────
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#070c16",
        plot_bgcolor="#050b14",
        font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
        title=dict(
            text=(
                "TIM Solver — Motor Validation  │  "
                "<span style='color:#00d4a8'>teal/blue = C ref (solid)</span>  │  "
                "<span style='color:#f07030'>orange/amber = VHDL Q14.28 (dashed)</span>  │  "
                "<span style='color:rgba(100,180,255,0.7)'>■ shaded = VHDL window</span>"
            ),
            font=dict(size=12),
            x=0.5, xanchor="center",
        ),
        legend=dict(
            orientation="v",
            yanchor="top", y=1.0,
            xanchor="left", x=1.02,
            font=dict(size=10),
            bgcolor="rgba(10,20,40,0.85)",
            bordercolor="#2a3f55",
            borderwidth=1,
            tracegroupgap=8,
            groupclick="toggleitem",
        ),
        height=900,
        margin=dict(l=80, r=200, t=70, b=40),
    )

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"Report saved: {out_path}")


# ---------------------------------------------------------------------------
# Compare-only report (reads combined CSV, no C model re-run)
# ---------------------------------------------------------------------------
def _build_compare_only_report(
    vhdl_rows: list[dict],
    out_path: Path,
    title_suffix: str = "",
) -> None:
    """Single-column 6-row VHDL vs C ref comparison from a combined CSV."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("ERROR: plotly not installed.  Run: uv add plotly")
        sys.exit(1)

    C_REF_A = "#00d4a8"
    C_REF_B = "#4da8e8"
    C_VH_A  = "#f07030"
    C_VH_B  = "#f0c040"
    C_ERR_A = "#ff6b6b"
    C_ERR_B = "#ffa07a"

    rows = _downsample(vhdl_rows, 4000)
    t = [r["t_us"] for r in rows]

    titles = [
        "① Applied Voltages  vα, vβ  [V]",
        "② Stator Current  iα  [A]  — C ref vs VHDL",
        "③ Stator Current  iβ  [A]  — C ref vs VHDL",
        "④ Rotor Flux  ψα, ψβ  [Wb]  — C ref vs VHDL",
        "⑤ Mechanical Speed  ωm  [RPM]  — C ref vs VHDL",
        "⑥ Error (VHDL − C ref):  iα, iβ  [A]",
    ]
    ylabels = ["Voltage [V]", "iα [A]", "iβ [A]", "Flux [Wb]", "Speed [RPM]", "Error [A]"]

    fig = make_subplots(rows=6, cols=1, shared_xaxes=True,
                        subplot_titles=titles, vertical_spacing=0.05)

    _co_groups: set[str] = set()  # groups that already have a title

    def _tr(x, y, name, color, dash="solid", width=1.6, row=1, group=None, gtitle=None):
        lg = group or name
        kw: dict = {}
        if gtitle and lg not in _co_groups:
            kw["legendgrouptitle_text"] = gtitle
            kw["legendgrouptitle"] = dict(
                text=gtitle, font=dict(size=10, color="#8ba8c8", family="IBM Plex Mono, monospace")
            )
            _co_groups.add(lg)
        fig.add_trace(go.Scatter(
            x=x, y=y, name=name,
            legendgroup=lg,
            line=dict(color=color, width=width, dash=dash),
            **kw,
        ), row=row, col=1)

    va_a = [_clarke_alpha(r["va"], r["vb"], r["vc"]) for r in rows]
    va_b = [_clarke_beta (r["va"], r["vb"], r["vc"]) for r in rows]

    _tr(t, va_a, "vα", C_REF_A,        row=1, group="Input Voltages", gtitle="Input Voltages")
    _tr(t, va_b, "vβ", C_REF_B, "dash", row=1, group="Input Voltages")

    _tr(t, [r["ref_i_alpha"]     for r in rows], "iα", C_REF_A,        row=2, group="C Reference", gtitle="C Reference Model")
    _tr(t, [r["vhdl_i_alpha"]    for r in rows], "iα", C_VH_A, "dash", row=2, group="VHDL DUT",   gtitle="VHDL Q14.28 DUT")

    _tr(t, [r["ref_i_beta"]      for r in rows], "iβ", C_REF_B,        row=3, group="C Reference")
    _tr(t, [r["vhdl_i_beta"]     for r in rows], "iβ", C_VH_B, "dash", row=3, group="VHDL DUT")

    _tr(t, [r["ref_flux_alpha"]  for r in rows], "ψα", C_REF_A,        row=4, group="C Reference")
    _tr(t, [r["vhdl_flux_alpha"] for r in rows], "ψα", C_VH_A, "dash", row=4, group="VHDL DUT")
    _tr(t, [r["ref_flux_beta"]   for r in rows], "ψβ", C_REF_B,        row=4, group="C Reference")
    _tr(t, [r["vhdl_flux_beta"]  for r in rows], "ψβ", C_VH_B, "dash", row=4, group="VHDL DUT")

    _tr(t, [_rpm(r["ref_speed"])  for r in rows], "ωm", C_REF_A,        row=5, group="C Reference")
    _tr(t, [_rpm(r["vhdl_speed"]) for r in rows], "ωm", C_VH_A, "dash", row=5, group="VHDL DUT")

    err_alpha = [r["vhdl_i_alpha"] - r["ref_i_alpha"] for r in rows]
    err_beta  = [r["vhdl_i_beta"]  - r["ref_i_beta"]  for r in rows]
    mae_a = sum(abs(e) for e in err_alpha) / len(err_alpha)
    mae_b = sum(abs(e) for e in err_beta)  / len(err_beta)
    _tr(t, err_alpha, f"err iα  MAE={mae_a:.1e} A", C_ERR_A,        width=1.2, row=6, group="Error (VHDL − C ref)", gtitle="Error (VHDL − C ref)")
    _tr(t, err_beta,  f"err iβ  MAE={mae_b:.1e} A", C_ERR_B, "dot", width=1.2, row=6, group="Error (VHDL − C ref)")
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.25)", width=0.7, dash="dot"), row=6, col=1)

    fig.update_xaxes(title_text="Time [µs]", row=6, col=1)
    for i, lbl in enumerate(ylabels, 1):
        fig.update_yaxes(title_text=lbl, row=i, col=1)
    for row in range(1, 7):
        fig.update_xaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)
        fig.update_yaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#070c16", plot_bgcolor="#050b14",
        font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
        title=dict(
            text=(
                f"TIM Solver — VHDL Q14.28 vs C Reference{title_suffix}  │  "
                "<span style='color:#00d4a8'>teal/blue = C ref (solid)</span>  │  "
                "<span style='color:#f07030'>orange/amber = VHDL (dashed)</span>"
            ),
            font=dict(size=12), x=0.5, xanchor="center",
        ),
        legend=dict(
            orientation="v",
            yanchor="top", y=1.0,
            xanchor="left", x=1.02,
            font=dict(size=10),
            bgcolor="rgba(10,20,40,0.85)",
            bordercolor="#2a3f55",
            borderwidth=1,
            tracegroupgap=8,
            groupclick="toggleitem",
        ),
        height=1050,
        margin=dict(l=80, r=200, t=70, b=40),
    )

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"Report saved: {out_path}")
    print(f"  Error stats — iα MAE={mae_a:.4e} A   iβ MAE={mae_b:.4e} A")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate motor startup report (C model + optional VHDL overlay)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # V/F ramp — C model 2 s, overlay VHDL V/F window
  uv run python scripts/vf_report.py --overlay

  # Pure sine 60 Hz — C model 200 ms (shows ~12 cycles), overlay VHDL sine window
  uv run python scripts/vf_report.py --sine --duration 0.2 --overlay \\
      --vhdl-csv reports/sine_vhdl_vs_ref.csv --out reports/sine_report.html

  # C model only, no VHDL
  uv run python scripts/vf_report.py --duration 2.0

  # Compare-only: read combined CSV (vhdl_* + ref_* columns), no C model re-run
  uv run python scripts/vf_report.py --compare-only \\
      --vhdl-csv reports/ref_vhdl_vs_ref.csv --out reports/ref_report.html
""",
    )
    parser.add_argument("--compare-only", action="store_true",
                        help="Read combined CSV (vhdl_* + ref_* cols) and generate comparison "
                             "report without re-running the C model")
    parser.add_argument("--duration",  type=float, default=1.5,
                        help="C model simulation duration [s] (default: 1.5)")
    parser.add_argument("--acc-ramp",  type=float, default=ACC_RAMP_HZ_S,
                        help=f"V/F frequency ramp rate [Hz/s] (default: {ACC_RAMP_HZ_S})")
    parser.add_argument("--tload",     type=float, default=TLOAD_NM,
                        help="Load torque [N·m] (default: 0)")
    parser.add_argument("--sine",      action="store_true",
                        help="Use pure 60 Hz sine stimulus instead of V/F ramp")
    parser.add_argument("--freq",      type=float, default=F_NOMINAL_HZ,
                        help=f"Frequency for --sine mode [Hz] (default: {F_NOMINAL_HZ})")
    parser.add_argument("--overlay",   action="store_true",
                        help="Overlay VHDL CSV data on the report")
    parser.add_argument("--vhdl-csv",  type=str, default=None,
                        help="Path to VHDL CSV (default: reports/vf_vhdl_vs_ref.csv or "
                             "reports/sine_vhdl_vs_ref.csv depending on --sine)")
    parser.add_argument("--out",       type=str, default=None,
                        help="Output HTML path (default: reports/vf_report.html or "
                             "reports/sine_report.html)")
    parser.add_argument("--no-html",   action="store_true",
                        help="Skip HTML generation (CSV only)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Compare-only mode: read combined CSV, no C model simulation ───────────
    if args.compare_only:
        vhdl_csv_path = Path(args.vhdl_csv) if args.vhdl_csv else REPORTS_DIR / "ref_vhdl_vs_ref.csv"
        out_path      = Path(args.out)       if args.out       else REPORTS_DIR / "ref_report.html"
        if not vhdl_csv_path.exists():
            print(f"ERROR: CSV not found: {vhdl_csv_path}", file=sys.stderr)
            sys.exit(1)
        with vhdl_csv_path.open() as f:
            raw = list(csv.DictReader(f))
        float_keys = [k for k in raw[0] if k != "step"]
        for r in raw:
            for k in float_keys:
                r[k] = float(r[k])
        print(f"Loaded CSV: {vhdl_csv_path} ({len(raw)} rows)")
        _build_compare_only_report(raw, out_path)
        return

    # ── Determine paths ───────────────────────────────────────────────────────
    if args.sine:
        default_vhdl_csv = REPORTS_DIR / "sine_vhdl_vs_ref.csv"
        default_out      = REPORTS_DIR / "sine_report.html"
        default_ref_csv  = REPORTS_DIR / "sine_ref_model.csv"
        title_suffix     = f", 60 Hz pure sine"
    else:
        default_vhdl_csv = REPORTS_DIR / "vf_vhdl_vs_ref.csv"
        default_out      = REPORTS_DIR / "vf_report.html"
        default_ref_csv  = REPORTS_DIR / "vf_ref_model.csv"
        title_suffix     = f", V/F ramp {args.acc_ramp:.0f} Hz/s"

    vhdl_csv_path = Path(args.vhdl_csv) if args.vhdl_csv else default_vhdl_csv
    out_path      = Path(args.out)      if args.out      else default_out

    # ── Load VHDL CSV (if overlay requested) ─────────────────────────────────
    vhdl_rows_preload = None
    if args.overlay:
        if vhdl_csv_path.exists():
            with vhdl_csv_path.open() as f:
                raw = list(csv.DictReader(f))
            float_keys = [k for k in raw[0] if k != "step"]
            for r in raw:
                for k in float_keys:
                    r[k] = float(r[k])
            vhdl_rows_preload = raw
            vhdl_dur_us = max(r["t_us"] for r in vhdl_rows_preload)
            print(f"VHDL CSV loaded: {vhdl_csv_path} "
                  f"({len(vhdl_rows_preload)} rows, duration={vhdl_dur_us:.1f} µs)")
        else:
            print(f"WARNING: VHDL CSV not found at {vhdl_csv_path} — running C model only.")

    # NOTE: C model always runs for args.duration (NOT capped to VHDL window).
    # This lets Section A show the full motor startup with visible sinusoids.

    # ── Build C model stimulus ────────────────────────────────────────────────
    params = IMPhysicalParams.defaults()
    ref    = InductionMotorReferenceModel(params=params, backend="auto")

    if args.sine:
        stimulus = SineControl(
            frequency_hz  = args.freq,
            v_peak        = V_PEAK_NOMINAL,
            ts            = params.ts,
            initial_theta = math.pi / 4,
            tload         = args.tload,
        )
    else:
        stimulus = VFControl(
            f_nominal      = F_NOMINAL_HZ,
            v_peak_nominal = V_PEAK_NOMINAL,
            acc_ramp_hz_s  = args.acc_ramp,
            ts             = params.ts,
            tload          = args.tload,
        )

    # ── Run C model ───────────────────────────────────────────────────────────
    total_steps = int(args.duration / params.ts)
    decimate    = max(1, total_steps // 50_000)
    dur_str     = f"{args.duration*1e6:.1f} µs" if args.duration < 0.01 else f"{args.duration:.3f} s"
    print(f"Running C reference model: {total_steps:,} steps "
          f"({dur_str} motor time, 1 point per {decimate} steps) ...")

    ref_rows: list[dict] = []
    fieldnames = [
        "t_s", "va", "vb", "vc", "f_ref_hz",
        "i_a", "i_b", "i_c",
        "i_alpha", "i_beta",
        "flux_alpha", "flux_beta",
        "speed_mech", "speed_elec",
        "torque",
    ]

    with default_ref_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for step in range(total_steps):
            va, vb, vc = stimulus.step()
            s = ref.step(va, vb, vc, stimulus.tload)

            if step % decimate == 0:
                row = {
                    "t_s":        step * params.ts,
                    "va": va, "vb": vb, "vc": vc,
                    "f_ref_hz":   stimulus.f_ref,
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

            if step % max(1, total_steps // 10) == 0:
                pct = 100 * step // total_steps
                f_disp = getattr(stimulus, "f_ref", args.freq)
                print(f"  {pct:3d}%  t={step*params.ts:.4f}s  "
                      f"f={f_disp:.1f} Hz  "
                      f"ωm={s.speed_mech:.2f} rad/s  "
                      f"Te={s.torque:.3f} N·m  "
                      f"ia={s.i_a:.4f} A")

    print(f"Reference CSV: {default_ref_csv} ({len(ref_rows)} rows)")

    if args.no_html:
        return

    if vhdl_rows_preload is not None:
        _build_compare_only_report(vhdl_rows_preload, out_path, title_suffix=title_suffix)
    else:
        _build_report(ref_rows, None, out_path, title_suffix=title_suffix)


if __name__ == "__main__":
    main()
