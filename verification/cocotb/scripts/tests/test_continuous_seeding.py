"""Unit tests for run_one's continuous single-seed replay.

Regression coverage for a methodology bug: run_one used to seed the C model
independently at the start of EACH window ("partida" from t=0, "regime" from
the window's own start deep into the capture), reusing the FPGA's own
(already SVF-filtered) telemetry as the seed each time. Re-seeding mid-run
injects a transient that has nothing to do with the motor -- it is the model
resettling from a fresh initial condition -- and that transient dominated the
"regime" window's error. A single continuous run, seeded once at the
capture's true rest state (t=0, all zero) and never reset, removes the
artifact entirely: measured on a real capture, regime NRMSE dropped from
~5% to ~2.3% and the model's steady-state speed became exact, purely from
not re-seeding (independent of the Ts fix in test_quantized_ts.py).
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hilbin_vs_c as hvc

POS, ZERO = 3, 6


# A coarse ts (not the real 130ns) keeps these structural tests fast: they
# check call counts and dict keys, not physical accuracy, and run_one refuses
# captures shorter than 0.1s regardless of step size.
_FAST_PARAMS = hvc.IMPhysicalParams(
    rs=0.4396, rr=0.2826, lm=109.9442e-3, ls=3.1364e-3, lr=6.3264e-3,
    j=0.4, npp=2.0, ts=10e-6,
)


def _make_hilbin(tmp_path: Path, duration_s: float = 0.15, n_fpga: int = 200,
                 n_pwm: int = 100, clock_hz: int = 100_000_000) -> Path:
    fpga_t = np.linspace(0.0, duration_s, n_fpga)
    meta_bytes = json.dumps({
        "version": 2, "date": "2026-01-01T00:00:00Z", "name": "test",
        "sample_count": n_fpga, "pwm_count": n_pwm, "raw": True, "clock_hz": clock_hz,
    }).encode()
    pre = b"HILDATA\x02" + struct.pack("<I", len(meta_bytes)) + meta_bytes
    header = pre + b"\x00" * (((len(pre) + 7) & ~7) - len(pre))

    fpga_arr = np.zeros((n_fpga, 7), dtype="<f4")
    fpga_arr[:, 0] = fpga_t.astype("<f4")
    # A non-degenerate ia/ib sinusoid, or best_lag's cross-correlation on
    # all-zero current finds an arbitrary (clipped) lag and every window ends
    # up sliced empty after the shift -- a fixture artifact, not real
    # behaviour to test against.
    fpga_arr[:, 1] = (10.0 * np.sin(2 * np.pi * 60.0 * fpga_t)).astype("<f4")
    fpga_arr[:, 2] = (10.0 * np.cos(2 * np.pi * 60.0 * fpga_t)).astype("<f4")
    fpga_arr[:, 5] = 188.0  # speed, nonzero so windows aren't trivially empty

    pwm_t_cycles = np.linspace(0, duration_s * clock_hz, n_pwm).astype("<u4")
    pwm_bytes = b"".join(
        struct.pack("<I", int(c)) + bytes([POS if i % 2 == 0 else ZERO, ZERO, ZERO, 0])
        for i, c in enumerate(pwm_t_cycles)
    )
    body = (struct.pack("<I", n_fpga) + fpga_arr.tobytes()
            + struct.pack("<I", n_pwm) + pwm_bytes)
    path = tmp_path / "test.hilbin"
    path.write_bytes(header + body)
    return path


@pytest.fixture(autouse=True)
def _no_file_output(monkeypatch):
    """run_one writes PNG/HTML/npz per window; skip that I/O in these tests."""
    monkeypatch.setattr(hvc, "make_png", lambda *a, **k: None)
    monkeypatch.setattr(hvc, "make_report_light", lambda *a, **k: None)
    monkeypatch.setattr(hvc, "_save_npz", lambda *a, **k: None)


def test_run_one_seeds_only_once_at_capture_start(tmp_path, monkeypatch):
    path = _make_hilbin(tmp_path)
    seed_calls = []
    real_seed_at = hvc._seed_at

    def spy_seed_at(fpga, t_start):
        seed_calls.append(t_start)
        return real_seed_at(fpga, t_start)

    monkeypatch.setattr(hvc, "_seed_at", spy_seed_at)

    hvc.run_one(path, vdc=1240.0, tload=0.0, out_root=tmp_path / "out", window=0.06, params=_FAST_PARAMS)

    assert seed_calls == [0.0], (
        f"expected exactly one seed at t=0 (capture rest state), got {seed_calls} -- "
        "re-seeding per window reintroduces the settling-transient artifact"
    )


def test_run_one_calls_the_c_model_only_once_for_the_whole_capture(tmp_path, monkeypatch):
    """Two windows must come from slicing ONE continuous trajectory, not two
    independent simulations."""
    path = _make_hilbin(tmp_path)
    calls = []
    real = hvc.run_c_model_seeded

    def spy(*args, **kwargs):
        calls.append((args[3], args[4]))  # (t_start, t_end)
        return real(*args, **kwargs)

    monkeypatch.setattr(hvc, "run_c_model_seeded", spy)

    hvc.run_one(path, vdc=1240.0, tload=0.0, out_root=tmp_path / "out", window=0.06, params=_FAST_PARAMS)

    assert len(calls) == 1, f"expected one continuous replay call, got {len(calls)}: {calls}"
    t_start, t_end = calls[0]
    assert t_start == 0.0
    assert t_end > 0.14  # spans (close to) the whole capture, not just one window


def test_metrics_include_absolute_mae_alongside_nrmse(tmp_path, monkeypatch):
    """NRMSE alone is misleading across windows with different load: it
    normalizes by that window's own reference RMS, so the SAME absolute
    error reads as a bigger percentage under a smaller no-load current.
    MAE in amps must be reported so windows are comparable in absolute terms."""
    path = _make_hilbin(tmp_path)
    # This fixture's synthetic ia/ib bear no relation to what the C model
    # actually computes from its own PWM events, so cross-correlation lag is
    # meaningless noise here; pin it so the windows land on real data instead
    # of an arbitrary (possibly near-clipped) shift.
    monkeypatch.setattr(hvc.L4, "best_lag", lambda *a, **k: 0.0)

    out = hvc.run_one(path, vdc=1240.0, tload=0.0, out_root=tmp_path / "out", window=0.06, params=_FAST_PARAMS)

    for label in ("partida", "regime"):
        assert label in out, f"missing {label} in {out.keys()}"
        m = out[label]
        assert "ia_mae" in m, f"{label} metrics missing ia_mae: {m.keys()}"
        assert "ib_mae" in m, f"{label} metrics missing ib_mae: {m.keys()}"
        assert isinstance(m["ia_mae"], float)


def test_load_step_case_still_uses_one_continuous_run(tmp_path, monkeypatch):
    """Grupo B (load step mid-run) must also be a single continuous replay
    with a time-varying tload -- not two separately-seeded passes."""
    path = _make_hilbin(tmp_path)
    calls = []
    real = hvc.run_c_model_seeded

    def spy(*args, **kwargs):
        calls.append((args[3], args[4]))
        return real(*args, **kwargs)

    monkeypatch.setattr(hvc, "run_c_model_seeded", spy)

    hvc.run_one(path, vdc=1240.0, tload=10.0, out_root=tmp_path / "out", window=0.06, params=_FAST_PARAMS,
               tload2=50.0, t_step_s=0.08)

    assert len(calls) == 1, f"expected one continuous replay call, got {len(calls)}: {calls}"
