"""Unit tests for the load-step schedule (Grupo B captures with a mid-run
torque step), which replaces running hilbin_vs_c twice with two constant
--tload values and keeping only the window each run happened to get right.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hilbin_vs_c as hvc


def test_schedule_returns_pre_before_step():
    sched = hvc.make_load_step(tload_pre=29.18, tload_post=87.54, t_step_s=0.6)
    assert sched(0.0) == 29.18
    assert sched(0.599) == 29.18


def test_schedule_returns_post_at_and_after_step():
    sched = hvc.make_load_step(tload_pre=29.18, tload_post=87.54, t_step_s=0.6)
    assert sched(0.6) == 87.54
    assert sched(1.0) == 87.54


def test_run_c_model_seeded_accepts_callable_tload(monkeypatch):
    """The C model must actually receive the scheduled value at each step, not
    a constant -- this is what a plain float tload would silently do wrong."""
    seen_tloads = []

    class FakeState:
        i_alpha = i_beta = flux_alpha = flux_beta = speed_mech = 0.0

    class FakeModel:
        backend_name = "fake"

        def __init__(self, params, backend):
            class Priv:
                class Out:
                    is_alpha = is_beta = fluxR_alpha = fluxR_beta = wm = wr = 0.0
                out = Out()
            self._impl = type("Impl", (), {"_model": type("M", (), {"priv": None})()})()

        def step(self, va, vb, vc, tload):
            seen_tloads.append(tload)
            return FakeState()

    import ctypes
    monkeypatch.setattr(hvc, "InductionMotorReferenceModel", FakeModel)
    monkeypatch.setattr(ctypes, "cast", lambda *a, **k: type("R", (), {"contents": type("C", (), {
        "out": type("O", (), {"is_alpha": 0.0, "is_beta": 0.0, "fluxR_alpha": 0.0,
                              "fluxR_beta": 0.0, "wm": 0.0, "wr": 0.0})()
    })()})())

    pwm = {"t": np.array([0.0, 1.0]), "a": np.array([3, 3]), "b": np.array([6, 6]), "c": np.array([6, 6])}
    seed = {"ia": 0.0, "ib": 0.0, "flux_a": 0.0, "flux_b": 0.0, "speed": 0.0}
    sched = hvc.make_load_step(tload_pre=10.0, tload_post=50.0, t_step_s=0.5)
    params = hvc.FIRMWARE_DEFAULT_PARAMS.__class__(
        rs=1, rr=1, lm=1, ls=1, lr=1, j=1, npp=1, ts=0.1,
    )

    hvc.run_c_model_seeded(pwm, vdc=1240.0, params=params, t_start=0.0, t_end=1.0,
                           seed=seed, tload=sched, output_hz=10.0)

    assert seen_tloads[0] == 10.0, "first step must use the pre-step load"
    assert seen_tloads[-1] == 50.0, "last step must use the post-step load"
    assert 10.0 in seen_tloads and 50.0 in seen_tloads


def test_run_c_model_seeded_still_accepts_constant_float_tload(monkeypatch):
    """Backward compatibility: existing callers passing a plain float must be
    unaffected by the callable-tload support."""
    seen_tloads = []

    class FakeState:
        i_alpha = i_beta = flux_alpha = flux_beta = speed_mech = 0.0

    class FakeModel:
        backend_name = "fake"

        def __init__(self, params, backend):
            self._impl = type("Impl", (), {"_model": type("M", (), {"priv": None})()})()

        def step(self, va, vb, vc, tload):
            seen_tloads.append(tload)
            return FakeState()

    import ctypes
    monkeypatch.setattr(hvc, "InductionMotorReferenceModel", FakeModel)
    monkeypatch.setattr(ctypes, "cast", lambda *a, **k: type("R", (), {"contents": type("C", (), {
        "out": type("O", (), {"is_alpha": 0.0, "is_beta": 0.0, "fluxR_alpha": 0.0,
                              "fluxR_beta": 0.0, "wm": 0.0, "wr": 0.0})()
    })()})())

    pwm = {"t": np.array([0.0, 1.0]), "a": np.array([3, 3]), "b": np.array([6, 6]), "c": np.array([6, 6])}
    seed = {"ia": 0.0, "ib": 0.0, "flux_a": 0.0, "flux_b": 0.0, "speed": 0.0}
    params = hvc.FIRMWARE_DEFAULT_PARAMS.__class__(rs=1, rr=1, lm=1, ls=1, lr=1, j=1, npp=1, ts=0.1)

    hvc.run_c_model_seeded(pwm, vdc=1240.0, params=params, t_start=0.0, t_end=0.5,
                           seed=seed, tload=42.0, output_hz=10.0)

    assert all(v == 42.0 for v in seen_tloads)
