#!/usr/bin/env python3
"""Offline L4 validation — C reference model vs a recorded .hilbin capture.

Reuses the live ``fpga_vs_c.py`` machinery (C model via ctypes, PWM-fed replay,
cross-correlation alignment, metrics, HTML report) but sources the FPGA
trajectory and the PWM gate stream from a recorded ``.hilbin`` file instead of a
live board. Self-contained: the captured PWM events are replayed through the C
model, so the original V/F command parameters are not needed.

Usage (from verification/cocotb/):
    uv run python scripts/hilbin_vs_c.py ../../apps/hil-go/runs/capture_XXXX.hilbin
    uv run python scripts/hilbin_vs_c.py --all          # batch every runs/*.hilbin
    uv run python scripts/hilbin_vs_c.py FILE --vdc 1240 --tload 0
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models.im_reference_model import (  # noqa: E402
    IMPhysicalParams,
    InductionMotorReferenceModel,
    _CIMPrivateData,
)
import fpga_vs_c as L4  # noqa: E402  (reuse replay + metrics + report helpers)

# ── Gap reseed threshold ──────────────────────────────────────────────────────
# PWM gaps shorter than this are minor UDP jitter (handled by OOO sort).
# Gaps longer than this indicate FIFO overflow; the C model is reseeded from
# FPGA telemetry at the gap boundary to prevent divergence.
GAP_RESEED_THRESHOLD_S = 0.020   # 20 ms

RUNS_DIR = Path(__file__).resolve().parents[3] / "apps" / "hil-go" / "runs"
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "hilbin"

FIRMWARE_DEFAULT_PARAMS = IMPhysicalParams(
    rs=0.435,
    rr=0.2826,
    lm=109.9442e-3,
    ls=3.1364e-3,
    lr=6.3264e-3,
    j=0.192,
    npp=2.0,
    ts=26.0 / 200_000_000,
)

_SAMPLE_FLOATS = 7  # t, ia, ib, flux_a, flux_b, speed, pad
_PWM_DTYPE = np.dtype([("t", "<f4"), ("a", "u1"), ("b", "u1"), ("c", "u1"), ("pad", "u1")])


def parse_hilbin(path: Path):
    """Parse a .hilbin file → (metadata, fpga_dict, pwm_dict).

    Layout (little-endian), from apps/hil-go/internal/record/recorder.go:
        "HILDATA"(7) ver(1) metaLen(u32) metaJSON  → 8-byte aligned
        sampleCount(u32)  sampleCount × 28B (7×f32: t,ia,ib,flux_a,flux_b,speed,pad)
        pwmCount(u32)     pwmCount × 8B (f32 t, u8 a, u8 b, u8 c, u8 pad)
    """
    data = Path(path).read_bytes()
    if data[:7] != b"HILDATA":
        raise ValueError(f"{path}: not a HILDATA file (bad magic)")

    meta_len = struct.unpack_from("<I", data, 8)[0]
    meta = json.loads(data[12:12 + meta_len])

    pos = (12 + meta_len + 7) & ~7  # 8-byte alignment after header
    sample_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4

    raw = np.frombuffer(
        data, dtype="<f4", count=sample_count * _SAMPLE_FLOATS, offset=pos
    ).reshape(-1, _SAMPLE_FLOATS)
    pos += sample_count * _SAMPLE_FLOATS * 4

    fpga = {
        "t": np.ascontiguousarray(raw[:, 0], dtype=float),
        "ia": np.ascontiguousarray(raw[:, 1], dtype=float),
        "ib": np.ascontiguousarray(raw[:, 2], dtype=float),
        "flux_a": np.ascontiguousarray(raw[:, 3], dtype=float),
        "flux_b": np.ascontiguousarray(raw[:, 4], dtype=float),
        "speed": np.ascontiguousarray(raw[:, 5], dtype=float),
    }

    pwm_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    ev = np.frombuffer(data, dtype=_PWM_DTYPE, count=pwm_count, offset=pos)
    pwm = {
        "t": ev["t"].astype(float),
        "a": ev["a"].astype(int),
        "b": ev["b"].astype(int),
        "c": ev["c"].astype(int),
    }
    return meta, fpga, pwm


def _first_monotonic_len(t: np.ndarray) -> int:
    """Length of the leading strictly-increasing run of t.

    Multi-epoch captures rebase t per epoch, so t jumps backwards at an epoch
    boundary. We compare within the first epoch's contiguous segment to keep the
    two streams on one consistent timeline (epoch-aware splitting is future work).
    """
    if t.size < 2:
        return t.size
    drops = np.where(np.diff(t) <= 0)[0]
    return int(drops[0] + 1) if drops.size else t.size


def _clip_fpga(fpga: dict) -> dict:
    """Clip the FPGA trajectory to its first monotonic segment, rezeroed to 0."""
    n = _first_monotonic_len(fpga["t"])
    t0 = fpga["t"][0]
    return {k: (v[:n] - t0 if k == "t" else v[:n]) for k, v in fpga.items()}


def _rezero(arr: dict) -> dict:
    """Shift a trajectory's time vector so it starts at 0."""
    if arr["t"].size:
        arr = {**arr, "t": arr["t"] - arr["t"][0]}
    return arr


def _clip_pwm(pwm: dict, max_t: float) -> dict:
    """Rezero PWM time and keep only events within [0, max_t] (bounds replay)."""
    if not pwm["t"].size:
        return pwm
    t = pwm["t"] - pwm["t"][0]
    keep = t <= max_t
    return {"t": t[keep], "a": pwm["a"][keep], "b": pwm["b"][keep], "c": pwm["c"][keep]}


def _metrics(fpga, cmod, t_lo, t_hi) -> dict:
    """Per-channel metrics over [t_lo, t_hi], reusing fpga_vs_c helpers."""
    mf = (fpga["t"] >= t_lo) & (fpga["t"] <= t_hi)
    tf = fpga["t"][mf]
    out = {"window_s": [round(t_lo, 4), round(t_hi, 4)], "n_fpga": int(tf.size)}
    if tf.size < 8:
        out["error"] = "empty window"
        return out
    for key, fn in (("ia", L4.nrmse), ("ib", L4.nrmse),
                    ("flux_a", L4.mae), ("flux_b", L4.mae), ("speed", L4.mae)):
        c = np.interp(tf, cmod["t"], cmod[key])
        out[f"{key}_{fn.__name__}"] = round(float(fn(c, fpga[key][mf])), 5)
    a_f = L4.fundamental_amp(fpga["ia"][mf])
    a_c = L4.fundamental_amp(np.interp(tf, cmod["t"], cmod["ia"]))
    out["ia_fund_fpga"] = round(float(a_f), 4)
    out["ia_fund_c"] = round(float(a_c), 4)
    out["ia_fund_delta_pct"] = round(100.0 * (a_f - a_c) / max(a_c, 1e-9), 2)
    out["speed_mean_fpga"] = round(float(np.mean(fpga["speed"][mf])), 3)
    out["speed_mean_c"] = round(float(np.mean(np.interp(tf, cmod["t"], cmod["speed"]))), 3)
    return out


def _find_pwm_gaps(tev: np.ndarray, threshold_s: float) -> list[tuple[int, float]]:
    """Return (index_before_gap, gap_duration_s) for each gap > threshold_s.

    Only positive dt values exceeding the threshold are returned; out-of-order
    events (dt <= 0) are ignored here and handled by the upstream sort step.

    dt is rounded to nanosecond precision before comparison to eliminate
    IEEE-754 representation noise in float64 arithmetic (e.g. 1.020 - 1.0 can
    produce 0.020000000000000018 rather than exactly 0.020).
    """
    if len(tev) < 2:
        return []
    dt = np.diff(tev.astype(np.float64))
    mask = np.round(dt, 9) > threshold_s
    return [(int(i), float(dt[i])) for i in np.where(mask)[0]]


def _gate_to_v_rtl(g, vdc):
    """NPC gate-state voltage mapping used by HIL_AXI_Top.vhd.

    The FPGA intentionally models dead-time/zero states as half levels:
    POS=+Vdc/2, ZERO_P=+Vdc/4, ZERO_N=-Vdc/4, NEG=-Vdc/2.
    """
    if g in (3, 1):
        return 0.5 * vdc
    if g == 2:
        return 0.25 * vdc
    if g == 4:
        return -0.25 * vdc
    if g in (12, -1):
        return -0.5 * vdc
    return 0.0


def _svf_step(lp, bp, raw):
    """Floating-point equivalent of the RTL SVF telemetry anti-alias filter."""
    old_lp = lp
    old_bp = bp
    new_lp = old_lp + old_bp / 32.0
    new_bp = old_bp + raw / 32.0 - old_lp / 32.0 - (1.4375 * old_bp) / 32.0
    return new_lp, new_bp


def run_c_model_seeded(pwm, vdc, params, t_start, t_end, seed, fpga=None, tload=0.0,
                       output_hz=100_000.0, pwm_delay_s=0.0):
    """Replay [t_start, t_end] through the C model on the solver tick grid.

    The FPGA does not integrate from PWM edge to PWM edge. It samples the current
    NPC gate state when each TIM_Solver step is launched and holds that voltage
    for the solver step. Replaying on the same fixed grid avoids edge-interval
    rounding artefacts and leaves only a single phase/delay term to tune.
    """
    model = InductionMotorReferenceModel(params=params, backend="c")
    priv = ctypes.cast(model._impl._model.priv, ctypes.POINTER(_CIMPrivateData)).contents

    def _apply_seed(s: dict) -> None:
        priv.out.is_alpha = float(s["ia"])
        priv.out.is_beta = float(s["ib"])
        priv.out.fluxR_alpha = float(s["flux_a"])
        priv.out.fluxR_beta = float(s["flux_b"])
        priv.out.wm = float(s["speed"])
        priv.out.wr = float(s["speed"]) * params.npp

    _apply_seed(seed)

    ts = params.ts
    store_every = max(1, round((1.0 / output_hz) / ts))
    tev = pwm["t"]
    ga, gb, gc = pwm["a"], pwm["b"], pwm["c"]
    if tev.size < 1:
        return {"t": np.array([]), "ia": np.array([]), "ib": np.array([]),
                "flux_a": np.array([]), "flux_b": np.array([]), "speed": np.array([]),
                "backend": model.backend_name, "gap_count": 0, "gap_total_s": 0.0}

    T, IA, IB, FA, FB, SP = [], [], [], [], [], []
    svf_lp = np.array([seed["ia"], seed["ib"], seed["flux_a"], seed["flux_b"], seed["speed"]], dtype=float)
    svf_bp = np.zeros(5, dtype=float)

    gap_count = 0
    gap_total_s = 0.0
    gaps = _find_pwm_gaps(tev, GAP_RESEED_THRESHOLD_S)
    gap_by_end = {i + 1: dt for i, dt in gaps}
    next_gap_pos = 0

    n_steps = max(0, int(np.floor((t_end - t_start) / ts)))
    j = max(0, int(np.searchsorted(tev, t_start + pwm_delay_s, side="right")) - 1)
    for k in range(n_steps + 1):
        t = t_start + k * ts
        sample_t = t + pwm_delay_s
        while j + 1 < len(tev) and tev[j + 1] <= sample_t:
            j += 1
            if next_gap_pos < len(gaps) and gaps[next_gap_pos][0] + 1 == j:
                dt = gaps[next_gap_pos][1]
                next_gap_pos += 1
                if fpga is not None:
                    gap_seed = _seed_at(fpga, float(tev[j]))
                    _apply_seed(gap_seed)
                    svf_lp = np.array([gap_seed["ia"], gap_seed["ib"], gap_seed["flux_a"], gap_seed["flux_b"], gap_seed["speed"]], dtype=float)
                    svf_bp = np.zeros(5, dtype=float)
                    gap_count += 1
                    gap_total_s += dt
        vva = _gate_to_v_rtl(ga[j], vdc)
        vvb = _gate_to_v_rtl(gb[j], vdc)
        vvc = _gate_to_v_rtl(gc[j], vdc)
        st = model.step(vva, vvb, vvc, tload)
        raw = np.array([st.i_alpha, st.i_beta, st.flux_alpha, st.flux_beta, st.speed_mech], dtype=float)
        for fk in range(5):
            svf_lp[fk], svf_bp[fk] = _svf_step(svf_lp[fk], svf_bp[fk], raw[fk])
        if k % store_every == 0:
            T.append(t); IA.append(svf_lp[0]); IB.append(svf_lp[1])
            FA.append(svf_lp[2]); FB.append(svf_lp[3]); SP.append(svf_lp[4])

    return {
        "t": np.array(T), "ia": np.array(IA), "ib": np.array(IB),
        "flux_a": np.array(FA), "flux_b": np.array(FB), "speed": np.array(SP),
        "backend": model.backend_name,
        "gap_count": gap_count,
        "gap_total_s": round(gap_total_s, 4),
    }

def _seed_at(fpga: dict, t_start: float) -> dict:
    """FPGA state at the sample nearest t_start (the seed for the C model)."""
    i = int(np.searchsorted(fpga["t"], t_start))
    i = min(max(i, 0), fpga["t"].size - 1)
    return {k: float(fpga[k][i]) for k in ("ia", "ib", "flux_a", "flux_b", "speed")}


def _decim(t: np.ndarray, y: np.ndarray, target: int = 4000):
    """Stride-decimate (t, y) down to ~target points for lightweight plotting."""
    n = t.size
    if n <= target:
        return t, y
    step = max(1, n // target)
    return t[::step], y[::step]


_PLOT_SIG = [("ia", "iα [A]"), ("ib", "iβ [A]"), ("flux_a", "ψα [Wb]"), ("speed", "ωm [rad/s]")]


def make_report_light(fpga, cmod, out_html: Path, max_pts: int = 4000) -> None:
    """Decimated overlay (Scattergl + plotly.js via CDN) → small, fast-opening HTML.

    Metrics are computed on the full signal elsewhere; only the plot is thinned.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  (plotly ausente — pulando HTML)")
        return
    fig = make_subplots(rows=len(_PLOT_SIG), cols=1, shared_xaxes=True,
                        subplot_titles=[s[1] for s in _PLOT_SIG])
    for r, (k, _) in enumerate(_PLOT_SIG, 1):
        ct, cy = _decim(cmod["t"], cmod[k], max_pts)
        ft, fy = _decim(fpga["t"], fpga[k], max_pts)
        fig.add_trace(go.Scattergl(x=ct, y=cy, name=f"C {k}", line=dict(width=1.5)), row=r, col=1)
        fig.add_trace(go.Scattergl(x=ft, y=fy, name=f"FPGA {k}", mode="markers",
                                   marker=dict(size=3, opacity=0.6)), row=r, col=1)
    fig.update_layout(height=240 * len(_PLOT_SIG), template="plotly_dark",
                      title="C reference (linha) vs FPGA (pontos) — decimado")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_html), include_plotlyjs="cdn")
    print(f"  relatório: {out_html}")


def make_png(fpga, cmod, out_png: Path, title: str = "") -> None:
    """Static PNG overlay (matplotlib) — small, opens anywhere, good for the thesis."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib ausente — pulando PNG)")
        return
    fig, ax = plt.subplots(len(_PLOT_SIG), 1, figsize=(11, 9), sharex=True)
    for a, (k, lbl) in zip(ax, _PLOT_SIG):
        a.plot(cmod["t"], cmod[k], color="#3aa0ff", lw=1.4, label="Modelo C")
        a.plot(fpga["t"], fpga[k], ".", color="#ff6b4a", ms=2, alpha=0.6, label="FPGA")
        a.set_ylabel(lbl); a.grid(alpha=0.25); a.legend(loc="upper right", fontsize=8)
    if title:
        ax[0].set_title(title)
    ax[-1].set_xlabel("Tempo [s]")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    print(f"  png: {out_png}")


def _save_npz(fpga, cmod, out_npz: Path, max_pts: int = 4000) -> None:
    """Persist decimated trajectories so the HTML can be regenerated instantly."""
    data = {}
    for k in ("t", "ia", "ib", "flux_a", "flux_b", "speed"):
        ft, fy = _decim(fpga["t"], fpga[k], max_pts)
        ct, cy = _decim(cmod["t"], cmod[k], max_pts)
        data[f"fpga_{k}"] = fy if k != "t" else ft
        data[f"cmod_{k}"] = cy if k != "t" else ct
    np.savez_compressed(out_npz, **data)


def _win(fpga: dict, ta: float, tb: float) -> dict:
    m = (fpga["t"] >= ta) & (fpga["t"] <= tb)
    return {k: v[m] for k, v in fpga.items()}


def _params_from_args(args) -> IMPhysicalParams:
    return IMPhysicalParams(
        rs=args.rs,
        rr=args.rr,
        lm=args.lm,
        ls=args.ls,
        lr=args.lr,
        j=args.j,
        npp=args.npp,
        ts=args.ts,
    )


def run_one(path: Path, vdc: float, tload: float, out_root: Path, window: float = 0.5,
            params: IMPhysicalParams = FIRMWARE_DEFAULT_PARAMS, output_hz: float = 100_000.0,
            pwm_delay_s: float = 0.0, auto_pwm_delay_us: float = 0.0) -> dict:
    name = path.stem
    print(f"\n══ {name} ══")
    meta, fpga, pwm = parse_hilbin(path)
    print(f"  samples={fpga['t'].size}  pwm_events={pwm['t'].size}  clock_hz={meta.get('clock_hz')}")
    if fpga["t"].size < 8 or pwm["t"].size < 4:
        print("  captura sem dados suficientes — pulando")
        return {"capture": name, "error": "insufficient data"}

    fpga = _clip_fpga(fpga)
    pwm = _rezero(pwm)
    if pwm["t"].size > 1:
        _ord = np.argsort(pwm["t"], kind="stable")
        pwm = {k: v[_ord] for k, v in pwm.items()}
    seg_dur = float(fpga["t"][-1]) if fpga["t"].size else 0.0
    if seg_dur < 0.1 or pwm["t"].size < 4:
        print(f"  segmento monotônico curto demais ({seg_dur:.3f}s) — pulando")
        return {"capture": name, "error": "no usable monotonic segment"}

    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Seed the C model from the FPGA state at the window start, then replay only
    # that window — so steady state (late in long captures) is comparable cheaply.
    windows = {
        "partida": (0.0, min(window, seg_dur)),
        "regime": (max(0.0, seg_dur - window), seg_dur),
    }
    print(f"  duração do segmento = {seg_dur:.2f}s  (Vdc={vdc:.0f} V, J={params.j:g}, Rs={params.rs:g})")
    out = {
        "capture": name,
        "vdc": vdc,
        "tload": tload,
        "seg_dur_s": round(seg_dur, 3),
        "params": {
            "rs": params.rs, "rr": params.rr, "lm": params.lm, "ls": params.ls,
            "lr": params.lr, "j": params.j, "npp": params.npp, "ts": params.ts,
        },
        "comparison_notes": [
            "PWM replay uses the RTL NPC voltage mapping: POS=+Vdc/2, ZERO_P=+Vdc/4, ZERO_N=-Vdc/4, NEG=-Vdc/2.",
            "C outputs are passed through the same floating-point SVF form used by the FPGA telemetry path before metrics.",
            "If the .hilbin has no run metadata, firmware default motor parameters are used.",
            f"C replay output is stored at {output_hz:g} Hz for plotting and metrics interpolation.",
            "C replay samples captured PWM on the fixed solver tick grid, matching the FPGA input semantics.",
            f"PWM timestamp delay applied to replay: {pwm_delay_s * 1e6:+.1f} us.",
        ],
    }
    for label, (ta, tb) in windows.items():
        if tb - ta < 0.05:
            continue
        delay_s = pwm_delay_s
        delay_sweep = None
        if auto_pwm_delay_us > 0 and label == "regime":
            sweep = np.arange(-auto_pwm_delay_us, auto_pwm_delay_us + 0.1, 50.0) * 1e-6
            best = None
            # Use a very short tail slice; Python/ctypes is only a coarse sync estimator.
            swa = max(ta, tb - min(0.02, tb - ta))
            for cand in sweep:
                seed_s = _seed_at(fpga, swa)
                ctest = run_c_model_seeded(pwm, vdc, params, swa, tb, seed_s, fpga=fpga,
                                           tload=tload, output_hz=min(output_hz, 50_000.0),
                                           pwm_delay_s=float(cand))
                if ctest["t"].size < 8:
                    continue
                mtest = _metrics(_win(fpga, swa, tb), ctest, swa, tb)
                score = float(mtest.get("ia_nrmse", 1e9)) + float(mtest.get("ib_nrmse", 1e9))
                if best is None or score < best[0]:
                    best = (score, float(cand), mtest)
            if best is not None:
                delay_s = best[1]
                delay_sweep = {
                    "range_us": [-auto_pwm_delay_us, auto_pwm_delay_us],
                    "step_us": 50.0,
                    "selected_us": round(delay_s * 1e6, 3),
                    "score": round(best[0], 5),
                    "tail_metrics": best[2],
                }
                print(f"  [{label}] auto PWM delay = {delay_s * 1e6:+.1f} us")
        seed = _seed_at(fpga, ta)
        cmod = run_c_model_seeded(pwm, vdc, params, ta, tb, seed, fpga=fpga, tload=tload,
                                  output_hz=output_hz, pwm_delay_s=delay_s)
        if cmod["t"].size < 8:
            print(f"  [{label}] replay vazio — pulando")
            continue
        lag = L4.best_lag(fpga["t"], fpga["ia"], cmod["t"], cmod["ia"], max_lag_s=0.01)
        cmod["t"] = cmod["t"] + lag
        fwin = _win(fpga, ta, tb)
        m = _metrics(fwin, cmod, ta, tb)
        gaps_str = (f"  gaps={cmod['gap_count']}({cmod['gap_total_s']:.2f}s)"
                    if cmod["gap_count"] else "")
        print(f"  [{label} {ta:.2f}-{tb:.2f}s] iα NRMSE={m.get('ia_nrmse')}%  "
              f"lag={lag*1e3:+.2f}ms  backend={cmod['backend']}{gaps_str}")
        title = (f"{name} — {label} ({ta:.1f}–{tb:.1f}s) — FPGA vs Modelo C"
                 + (f"  iα NRMSE {m['ia_nrmse']:.1f}%" if m.get("ia_nrmse") else ""))
        make_png(fwin, cmod, out_dir / f"{label}.png", title)
        make_report_light(fwin, cmod, out_dir / f"{label}.html")
        _save_npz(fwin, cmod, out_dir / f"{label}.npz")
        m["pwm_delay_us"] = round(delay_s * 1e6, 3)
        if delay_sweep is not None:
            m["pwm_delay_sweep"] = delay_sweep
        m["pwm_gaps"] = {
            "count": cmod["gap_count"],
            "total_s": cmod["gap_total_s"],
        }
        out[label] = m

    (out_dir / "metrics.json").write_text(json.dumps(out, indent=2))
    print(f"  métricas: {out_dir / 'metrics.json'}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline FPGA(.hilbin) vs C reference report.")
    ap.add_argument("capture", nargs="?", help="path to a .hilbin file")
    ap.add_argument("--all", action="store_true", help=f"process every {RUNS_DIR}/*.hilbin")
    ap.add_argument("--vdc", type=float, default=1240.0, help="DC link [V] (default 1240)")
    ap.add_argument("--tload", type=float, default=0.0, help="load torque [N·m] (default 0)")
    ap.add_argument("--out", default=str(REPORTS_DIR), help="output root dir")
    ap.add_argument("--window", type=float, default=0.5,
                    help="replay window length per region [s] (default 0.5)")
    ap.add_argument("--output-hz", type=float, default=100_000.0,
                    help="C replay output sample rate for plots/metrics [Hz] (default 100000)")
    ap.add_argument("--pwm-delay-us", type=float, default=0.0,
                    help="delay added to PWM timestamps during replay [us] (default 0)")
    ap.add_argument("--auto-pwm-delay-us", type=float, default=0.0,
                    help="sweep +/- this delay on the regime tail and use the best PWM delay [us]")
    ap.add_argument("--ts", type=float, default=FIRMWARE_DEFAULT_PARAMS.ts,
                    help="solver step [s] (default firmware TIMER_STEPS/200MHz)")
    ap.add_argument("--rs", type=float, default=FIRMWARE_DEFAULT_PARAMS.rs)
    ap.add_argument("--rr", type=float, default=FIRMWARE_DEFAULT_PARAMS.rr)
    ap.add_argument("--lm", type=float, default=FIRMWARE_DEFAULT_PARAMS.lm)
    ap.add_argument("--ls", type=float, default=FIRMWARE_DEFAULT_PARAMS.ls)
    ap.add_argument("--lr", type=float, default=FIRMWARE_DEFAULT_PARAMS.lr)
    ap.add_argument("--j", type=float, default=FIRMWARE_DEFAULT_PARAMS.j)
    ap.add_argument("--npp", type=float, default=FIRMWARE_DEFAULT_PARAMS.npp)
    args = ap.parse_args()

    out_root = Path(args.out)
    if args.all:
        files = sorted(RUNS_DIR.glob("*.hilbin"))
    elif args.capture:
        files = [Path(args.capture)]
    else:
        ap.error("pass a .hilbin path or --all")

    if not files:
        ap.error("no .hilbin files found")

    summary = []
    for f in files:
        try:
            summary.append(run_one(f, args.vdc, args.tload, out_root, args.window, _params_from_args(args),
                                   args.output_hz, args.pwm_delay_us * 1e-6, args.auto_pwm_delay_us))
        except Exception as exc:  # keep batch going
            print(f"  ERRO em {f.name}: {exc}")
            summary.append({"capture": f.stem, "error": str(exc)})

    (out_root).mkdir(parents=True, exist_ok=True)
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n✓ resumo: {out_root / 'summary.json'}  ({len(summary)} captura(s))")


if __name__ == "__main__":
    main()
