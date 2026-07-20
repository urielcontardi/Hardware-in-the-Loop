"""Unit tests for the PWM dead-time repair in hilbin_vs_c.py.

Background: the PS drains the PL event FIFO with peek()/pop() over AXI, whose
read and write channels are independent. When a POP has not propagated before
the next PEEK, the PS reads the same FIFO entry twice and the following event
is consumed without being reported. When the lost event is a dead-time exit
(ZERO_P->ZERO), the replayed leg stays parked at +-Vdc/4 for the rest of the
carrier period instead of 0 V.

The repair rests on an FSM invariant, not on a fit: NPCGateDriver's ZERO_P/
ZERO_N are transient dead-time states, so a leg can never remain in one for
longer than the dead time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hilbin_vs_c as hvc

POS, ZERO_P, ZERO, ZERO_N, NEG = 3, 2, 6, 4, 12
DT = 0.52e-6  # dead time observed on hardware


def _pwm(events: list[tuple[float, int, int, int]]) -> dict:
    """Build a pwm dict from (t, a, b, c) tuples."""
    return {
        "t": np.array([e[0] for e in events], dtype=float),
        "a": np.array([e[1] for e in events], dtype=int),
        "b": np.array([e[2] for e in events], dtype=int),
        "c": np.array([e[3] for e in events], dtype=int),
    }


# ── clean streams are left alone ──────────────────────────────────────────────

def test_clean_stream_is_unchanged():
    """Dead-times of exactly DT are legal -> nothing inserted."""
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),
        (0.000100 + DT, ZERO, ZERO, ZERO),
        (0.001000, ZERO_P, ZERO, ZERO),
        (0.001000 + DT, POS, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 0
    np.testing.assert_array_equal(fixed["a"], pwm["a"])
    np.testing.assert_array_equal(fixed["t"], pwm["t"])


def test_empty_stream_does_not_crash():
    pwm = _pwm([])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)
    assert report["inserted"] == 0
    assert fixed["t"].size == 0


# ── the actual defect ─────────────────────────────────────────────────────────

def test_stuck_zero_p_gets_zero_inserted():
    """ZERO_P held ~900us: the lost ZERO exit is reinserted at entry+DT."""
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),   # dead-time entry; exit was lost
        (0.001000, ZERO_P, ZERO, ZERO),   # real event, ~900us later
        (0.001000 + DT, POS, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 1
    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["t"][i] == 0.000100 + DT
    assert fixed["a"][i] == ZERO


def test_stuck_zero_n_repairs_to_zero():
    pwm = _pwm([
        (0.000000, NEG, ZERO, ZERO),
        (0.000100, ZERO_N, ZERO, ZERO),
        (0.001000, ZERO_N, ZERO, ZERO),
        (0.001000 + DT, NEG, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 1
    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["a"][i] == ZERO


# ── a stuck dead-time always settles at ZERO ──────────────────────────────────

def test_stuck_entered_from_zero_still_settles_at_zero():
    """Entering from ZERO does not mean exiting to POS: below the minimum pulse
    width cmd falls again within the dead time and the pulse is suppressed.
    Restoring POS here measures ~5x worse against hardware."""
    pwm = _pwm([
        (0.000000, ZERO, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),   # entered from ZERO; exit lost
        (0.001000, POS, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 1
    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["a"][i] == ZERO


def test_entry_and_reentry_in_one_run_are_repaired_separately():
    """A run merges the POS->ZERO_P entry with a later re-entry; only the entry
    whose hold exceeds the dead time is repaired, and the re-entry survives."""
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),   # exit lost -> repaired to ZERO
        (0.001000, ZERO_P, ZERO, ZERO),   # re-entry, exits normally
        (0.001000 + DT, POS, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 1
    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["a"][i] == ZERO
    j = int(np.searchsorted(fixed["t"], 0.001000))
    assert fixed["a"][j] == ZERO_P, "re-entry must survive"


def test_inserted_event_preserves_other_phases():
    """Only the stuck phase is forced to ZERO; b/c keep their state."""
    pwm = _pwm([
        (0.000000, POS, NEG, ZERO),
        (0.000100, ZERO_P, NEG, ZERO),
        (0.001000, ZERO_P, NEG, ZERO),
        (0.001000 + DT, POS, NEG, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["a"][i] == ZERO
    assert fixed["b"][i] == NEG
    assert fixed["c"][i] == ZERO


def test_later_legit_dead_time_is_not_clobbered():
    """The ZERO->ZERO_P entry before POS is real and must survive the repair."""
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),   # stuck (exit lost)
        (0.001000, ZERO_P, ZERO, ZERO),   # legit dead-time entry going back up
        (0.001000 + DT, POS, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    j = int(np.searchsorted(fixed["t"], 0.001000))
    assert fixed["a"][j] == ZERO_P, "legit dead-time entry was overwritten"


def test_repairs_each_phase_independently():
    pwm = _pwm([
        (0.000000, POS, NEG, POS),
        (0.000100, ZERO_P, ZERO_N, POS),  # a and b both stuck
        (0.001000, ZERO_P, ZERO_N, POS),
        (0.001000 + DT, POS, NEG, POS),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["inserted"] == 2
    i = int(np.searchsorted(fixed["t"], 0.000100 + DT))
    assert fixed["a"][i] == ZERO
    assert fixed["b"][i] == ZERO


# ── duplicate phantom reads ───────────────────────────────────────────────────

def test_exact_duplicate_events_are_dropped():
    """A change-triggered FIFO cannot emit two identical consecutive events;
    they are phantom re-reads of the same entry."""
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),   # phantom duplicate
        (0.000100 + DT, ZERO, ZERO, ZERO),
    ])
    fixed, report = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)

    assert report["duplicates_dropped"] == 1
    assert fixed["t"].size == 3


def test_output_stays_time_sorted():
    pwm = _pwm([
        (0.000000, POS, ZERO, ZERO),
        (0.000100, ZERO_P, ZERO, ZERO),
        (0.001000, ZERO_P, ZERO, ZERO),
        (0.001000 + DT, POS, ZERO, ZERO),
        (0.002000, ZERO_P, ZERO, ZERO),
        (0.003000, ZERO_P, ZERO, ZERO),
        (0.003000 + DT, POS, ZERO, ZERO),
    ])
    fixed, _ = hvc.repair_pwm_dead_time_holds(pwm, dead_time_s=DT)
    assert np.all(np.diff(fixed["t"]) >= 0)


# ── dead-time estimation from data ────────────────────────────────────────────

def test_dead_time_is_estimated_from_the_stream_median():
    """Most dead-times are correct, so their median recovers DT."""
    events = [(0.0, POS, ZERO, ZERO)]
    t = 0.0
    for k in range(20):
        t = 0.001 * (k + 1)
        events.append((t, ZERO_P, ZERO, ZERO))
        events.append((t + DT, ZERO, ZERO, ZERO))
    pwm = _pwm(events)

    est = hvc._estimate_dead_time_s(pwm)
    assert abs(est - DT) < 0.05e-6
