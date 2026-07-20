"""Unit tests for the Q14.28-quantized solver timestep.

Ts=130ns (26 cycles @ 200MHz) is not exactly representable in Q14.28 fixed
point: 130ns * 2^28 = 34.8966, which the RTL rounds to 35 when baking the
integration coefficients. The hardware therefore actually integrates with
Ts=130.3852ns, not the nominal 130ns -- a deterministic +0.296% step-size
bias. Measured independently on real hardware and on an L2 VHDL simulation:
both settle to a no-load synchronous speed of 187.9387/187.9388 rad/s against
a true-60Hz synchronous speed of 188.4956 rad/s, a 0.2954% slip that matches
this quantization to 6 significant figures -- not solver/model error.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hilbin_vs_c as hvc


def test_quantized_ts_matches_hand_derivation():
    # 26/200e6 * 2**28 = 34.8966... -> rounds to 35 -> 35/2**28 s
    assert hvc._quantized_ts(cycles=26, clock_hz=200_000_000) == 35 / 2**28


def test_quantized_ts_is_larger_than_nominal():
    nominal = 26 / 200_000_000
    assert hvc._quantized_ts() > nominal


def test_quantized_ts_error_matches_measured_speed_offset():
    """The 0.296% Ts bias must reproduce the measured 0.2954% slip within
    round-off (both derived independently, so they should agree closely)."""
    nominal = 26 / 200_000_000
    quantized = hvc._quantized_ts()
    err_pct = (quantized / nominal - 1) * 100
    assert abs(err_pct - 0.2963) < 0.001


def test_quantized_ts_exact_value_in_seconds():
    assert abs(hvc._quantized_ts() - 130.385160446167e-9) < 1e-15


def test_firmware_default_params_keeps_true_tick_period():
    """params.ts paces run_c_model_seeded's loop (step count and which real
    PWM sample each tick reads) -- it must stay the TRUE 130ns hardware tick.
    Setting it to the quantized value was tried first and made no difference
    to any metric: n_steps and per-step Ts scale together, so total modeled
    time still equals real elapsed time regardless of which Ts is used for
    both roles at once. The bias only appears when the tick *count* is paced
    by the true period while each tick's *coefficients* assume the quantized
    one -- see model_ts in run_c_model_seeded."""
    assert hvc.FIRMWARE_DEFAULT_PARAMS.ts == 26.0 / 200_000_000


def test_run_one_defaults_model_ts_to_quantized():
    """The correction must be on by default for every caller of run_one, not
    an opt-in flag nobody remembers to pass."""
    import inspect
    default = inspect.signature(hvc.run_one).parameters["model_ts"].default
    assert default == hvc._quantized_ts()


def test_run_c_model_seeded_model_ts_only_affects_internal_integration(monkeypatch):
    """model_ts must change what Ts the constructed C model integrates with,
    while leaving the loop's own pacing (params.ts) untouched."""
    seen_ts = []

    class FakeState:
        i_alpha = i_beta = flux_alpha = flux_beta = speed_mech = 0.0

    class FakeModel:
        backend_name = "fake"

        def __init__(self, params, backend):
            seen_ts.append(params.ts)
            self._impl = type("Impl", (), {"_model": type("M", (), {"priv": None})()})()

        def step(self, va, vb, vc, tload):
            return FakeState()

    import ctypes
    monkeypatch.setattr(hvc, "InductionMotorReferenceModel", FakeModel)
    monkeypatch.setattr(ctypes, "cast", lambda *a, **k: type("R", (), {"contents": type("C", (), {
        "out": type("O", (), {"is_alpha": 0.0, "is_beta": 0.0, "fluxR_alpha": 0.0,
                              "fluxR_beta": 0.0, "wm": 0.0, "wr": 0.0})()
    })()})())

    pwm = {"t": np.array([0.0, 1.0]), "a": np.array([3, 3]), "b": np.array([6, 6]), "c": np.array([6, 6])}
    seed = {"ia": 0.0, "ib": 0.0, "flux_a": 0.0, "flux_b": 0.0, "speed": 0.0}
    params = hvc.FIRMWARE_DEFAULT_PARAMS.__class__(rs=1, rr=1, lm=1, ls=1, lr=1, j=1, npp=1, ts=130e-9)

    hvc.run_c_model_seeded(pwm, vdc=1240.0, params=params, t_start=0.0, t_end=1e-7,
                           seed=seed, tload=0.0, output_hz=10.0, model_ts=hvc._quantized_ts())

    assert seen_ts == [hvc._quantized_ts()]


def test_quantized_ts_falls_back_cleanly_for_exact_cases():
    """A cycles/clock_hz pair that IS exactly representable must round-trip
    with zero correction (sanity check on the rounding logic itself, using an
    arbitrary power-of-two-friendly pair rather than the real 26/200MHz)."""
    cycles, clock_hz = 32, 2**28  # Ts*2**28 = 32 exactly
    assert hvc._quantized_ts(cycles=cycles, clock_hz=clock_hz) == cycles / clock_hz
