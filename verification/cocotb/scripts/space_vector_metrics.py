#!/usr/bin/env python3
"""Space-vector (magnitude / phase / instantaneous frequency) error metrics.

Motivation
----------
NRMSE on i_alpha/i_beta mixes two distinct error sources: how far off the
*magnitude* of the current is, and how far off its *phase/timing* is. Because
this pipeline already works in the stationary alpha-beta frame, the stator
current is already a 2-D space vector: I(t) = i_alpha(t) + j*i_beta(t). Its
instantaneous magnitude |I(t)| and phase angle(I(t)) can be read off directly,
sample by sample, with no FFT — the same construction as an analytic signal,
for free, because two orthogonal axes are already available.

This script reads any combined *_vs_c.csv produced by the L2/L3 pipeline
(columns `ref_i_alpha/ref_i_beta` + `vhdl_i_alpha/vhdl_i_beta`, or the
`c_i_alpha/c_i_beta` naming used by the full-stack mock) and reports:

  - magnitude error (A, and % of a nominal current if given)
  - phase error (deg), computed as angle(I_dut * conj(I_ref)) so it wraps
    correctly instead of drifting the way a plain unwrap() difference would
  - instantaneous frequency (Hz) of both signals and their difference — shows
    whether the DUT tracks a V/f ramp at the same rate as the reference
  - a bounded cross-correlation lag estimate between the two i_alpha traces,
    to test for a systematic timing offset (formalizes what a manual phase
    sweep does by brute force)

Nothing here replaces NRMSE; it decomposes the same comparison into
magnitude vs. phase/timing so the two error sources aren't blended into one
percentage.

Usage (from verification/cocotb/):
    uv run python scripts/space_vector_metrics.py <csv> \\
        [--ref-prefix ref] [--dut-prefix vhdl] \\
        [--time-col t_us] [--time-scale 0.000001] \\
        [--nominal-current 22.5] \\
        [--out metrics.json] [--html overlay.html]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def _load_csv(path: Path, time_col: str, cols: list[str]) -> dict[str, np.ndarray]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        data: dict[str, list[float]] = {c: [] for c in [time_col, *cols]}
        for row in reader:
            for c in data:
                data[c].append(float(row[c]))
    return {c: np.asarray(v, dtype=float) for c, v in data.items()}


def _phase_error_deg(i_ref: np.ndarray, i_dut: np.ndarray) -> np.ndarray:
    """Wrapped phase error (dut - ref), in degrees, via complex ratio.

    Using angle(dut * conj(ref)) instead of unwrap(angle(dut)) -
    unwrap(angle(ref)) avoids unwrap() drift/discontinuity artifacts and
    always returns a value in (-180, 180].
    """
    ratio = i_dut * np.conj(i_ref)
    return np.degrees(np.angle(ratio))


def _instantaneous_freq_hz(phase_rad_unwrapped: np.ndarray, t: np.ndarray) -> np.ndarray:
    return np.gradient(phase_rad_unwrapped, t) / (2.0 * np.pi)


def _bounded_xcorr_lag(a: np.ndarray, b: np.ndarray, dt_median: float, max_lag_samples: int) -> dict:
    """Integer-sample lag in [-max_lag, max_lag] that maximizes correlation of b against a.

    Positive lag means `b` (the DUT) trails `a` (the reference) by that many
    samples. Bounded search keeps this O(max_lag * n) instead of O(n^2).
    """
    a = a - a.mean()
    b = b - b.mean()
    norm = np.sqrt((a ** 2).sum() * (b ** 2).sum())
    if norm <= 1e-12:
        return {"lag_samples": 0, "lag_s": 0.0, "peak_correlation": float("nan")}
    n = len(a)
    best_lag, best_corr = 0, -np.inf
    for lag in range(-max_lag_samples, max_lag_samples + 1):
        if lag >= 0:
            seg_a, seg_b = a[: n - lag], b[lag:]
        else:
            seg_a, seg_b = a[-lag:], b[: n + lag]
        if len(seg_a) < 10:
            continue
        corr = float(np.dot(seg_a, seg_b) / norm)
        if corr > best_corr:
            best_corr, best_lag = corr, lag
    return {"lag_samples": best_lag, "lag_s": best_lag * dt_median, "peak_correlation": best_corr}


def _stats(x: np.ndarray) -> dict:
    return {
        "mean": float(np.mean(x)),
        "mean_abs": float(np.mean(np.abs(x))),
        "rms": float(np.sqrt(np.mean(x ** 2))),
        "max_abs": float(np.max(np.abs(x))),
        "p95_abs": float(np.percentile(np.abs(x), 95)),
    }


def compute_space_vector_metrics(
    data: dict[str, np.ndarray],
    time_col: str,
    ref_alpha: str, ref_beta: str,
    dut_alpha: str, dut_beta: str,
    time_scale: float = 1.0,
    nominal_current_a: float | None = None,
    max_lag_samples: int = 50,
) -> dict:
    t = data[time_col] * time_scale
    i_ref = data[ref_alpha] + 1j * data[ref_beta]
    i_dut = data[dut_alpha] + 1j * data[dut_beta]

    mag_ref, mag_dut = np.abs(i_ref), np.abs(i_dut)
    mag_error = mag_dut - mag_ref
    phase_err_deg = _phase_error_deg(i_ref, i_dut)

    phase_ref_unwrapped = np.unwrap(np.angle(i_ref))
    phase_dut_unwrapped = np.unwrap(np.angle(i_dut))
    freq_ref = _instantaneous_freq_hz(phase_ref_unwrapped, t)
    freq_dut = _instantaneous_freq_hz(phase_dut_unwrapped, t)
    freq_error = freq_dut - freq_ref

    dt_median = float(np.median(np.diff(t)))
    lag = _bounded_xcorr_lag(data[ref_alpha], data[dut_alpha], dt_median, max_lag_samples)

    result = {
        "n_samples": int(len(t)),
        "dt_median_s": dt_median,
        "magnitude_error_a": _stats(mag_error),
        "phase_error_deg": _stats(phase_err_deg),
        "instantaneous_frequency_error_hz": _stats(freq_error),
        "lag_estimate": lag,
    }
    if nominal_current_a:
        result["magnitude_error_pct_inom"] = {
            k: v / nominal_current_a * 100.0
            for k, v in result["magnitude_error_a"].items()
            if k in ("mean_abs", "rms", "max_abs", "p95_abs")
        }
    result["_series"] = {
        "t": t, "mag_ref": mag_ref, "mag_dut": mag_dut, "mag_error": mag_error,
        "phase_error_deg": phase_err_deg, "freq_ref": freq_ref, "freq_dut": freq_dut,
        "freq_error": freq_error,
    }
    return result


def _build_plot(result: dict, out_path: Path, title_suffix: str = "") -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("plotly not installed — skipping HTML plot (metrics JSON still written).")
        return

    s = result["_series"]
    C_REF, C_DUT, C_ERR = "#00d4a8", "#f07030", "#ff6b6b"

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        subplot_titles=[
            "① Magnitude do vetor espacial |I| [A] — referência vs DUT",
            "② Erro de magnitude (DUT − ref) [A]",
            "③ Erro de fase instantânea (DUT − ref) [graus]",
            "④ Frequência instantânea [Hz] — referência vs DUT",
        ],
        vertical_spacing=0.07,
    )
    t = s["t"]
    fig.add_trace(go.Scatter(x=t, y=s["mag_ref"], name="|I| ref", line=dict(color=C_REF, width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=s["mag_dut"], name="|I| DUT", line=dict(color=C_DUT, width=1.4, dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=t, y=s["mag_error"], name="erro |I|", line=dict(color=C_ERR, width=1.2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=t, y=s["phase_error_deg"], name="erro de fase", line=dict(color=C_ERR, width=1.2)), row=3, col=1)
    fig.add_trace(go.Scatter(x=t, y=s["freq_ref"], name="f ref", line=dict(color=C_REF, width=1.4)), row=4, col=1)
    fig.add_trace(go.Scatter(x=t, y=s["freq_dut"], name="f DUT", line=dict(color=C_DUT, width=1.4, dash="dash")), row=4, col=1)
    for row in (2, 3):
        fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.25)", width=0.7, dash="dot"), row=row, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#070c16", plot_bgcolor="#050b14",
        font=dict(family="IBM Plex Mono, monospace", color="#ccd9ee", size=11),
        title=dict(text=f"Métricas de vetor espacial — magnitude/fase/frequência{title_suffix}", x=0.5, xanchor="center"),
        height=1050, margin=dict(l=70, r=40, t=70, b=40),
    )
    fig.update_yaxes(title_text="A", row=1, col=1)
    fig.update_yaxes(title_text="A", row=2, col=1)
    fig.update_yaxes(title_text="graus", row=3, col=1)
    fig.update_yaxes(title_text="Hz", row=4, col=1)
    fig.update_xaxes(title_text="Tempo [s]", row=4, col=1)
    for row in range(1, 5):
        fig.update_xaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)
        fig.update_yaxes(gridcolor="#1a2d42", linecolor="#2a3f55", row=row, col=1)

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"Plot saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, help="Combined *_vs_c.csv (ref_/vhdl_ or c_/vhdl_ i_alpha/i_beta columns)")
    parser.add_argument("--ref-prefix", default="ref", help="Column prefix for the reference signal (default: ref)")
    parser.add_argument("--dut-prefix", default="vhdl", help="Column prefix for the DUT signal (default: vhdl)")
    parser.add_argument("--time-col", default="t_us", help="Time column name (default: t_us)")
    parser.add_argument("--time-scale", type=float, default=1e-6, help="Multiply time column by this to get seconds (default: 1e-6)")
    parser.add_argument("--nominal-current", type=float, default=None, help="Nominal phase current [A] for %%I_n normalization (e.g. 22.5)")
    parser.add_argument("--max-lag", type=int, default=50, help="Max lag search window in samples (default: 50)")
    parser.add_argument("--out", type=Path, default=None, help="Output metrics JSON (default: <csv dir>/space_vector_metrics.json)")
    parser.add_argument("--html", type=Path, default=None, help="Output interactive plot HTML (default: <csv dir>/space_vector_overlay.html)")
    args = parser.parse_args()

    ref_alpha, ref_beta = f"{args.ref_prefix}_i_alpha", f"{args.ref_prefix}_i_beta"
    dut_alpha, dut_beta = f"{args.dut_prefix}_i_alpha", f"{args.dut_prefix}_i_beta"

    data = _load_csv(args.csv, args.time_col, [ref_alpha, ref_beta, dut_alpha, dut_beta])
    result = compute_space_vector_metrics(
        data, args.time_col, ref_alpha, ref_beta, dut_alpha, dut_beta,
        time_scale=args.time_scale,
        nominal_current_a=args.nominal_current,
        max_lag_samples=args.max_lag,
    )

    series = result.pop("_series")
    result["source_csv"] = str(args.csv)
    out_path = args.out or (args.csv.parent / "space_vector_metrics.json")
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Metrics saved: {out_path}")
    print(json.dumps(result, indent=2))

    html_path = args.html or (args.csv.parent / "space_vector_overlay.html")
    result["_series"] = series
    _build_plot(result, html_path, title_suffix=f" — {args.csv.parent.name}")


if __name__ == "__main__":
    main()
