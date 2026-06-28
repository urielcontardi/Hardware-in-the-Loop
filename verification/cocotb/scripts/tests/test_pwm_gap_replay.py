"""Unit tests for gap detection and replay logic in hilbin_vs_c.py.

Tests only _find_pwm_gaps (pure function — no motor model needed).
run_c_model_seeded is tested indirectly via run_one integration test
when a real .hilbin is present; otherwise skipped.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hilbin_vs_c as hvc


# ── _find_pwm_gaps ────────────────────────────────────────────────────────────

def test_no_gaps_returns_empty():
    tev = np.linspace(0.0, 1.0, 1000)
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert gaps == []


def test_single_gap_detected():
    """A 200 ms gap between indices 499 and 500 should be found."""
    t1 = np.linspace(0.0, 1.0, 500)
    t2 = np.linspace(1.200, 2.0, 500)
    tev = np.concatenate([t1, t2])
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert len(gaps) == 1
    idx, dt = gaps[0]
    assert idx == 499
    assert abs(dt - 0.2) < 0.01


def test_multiple_gaps_all_found():
    """Two separate 100 ms gaps are both detected."""
    t1 = np.linspace(0.0, 1.0, 200)
    t2 = np.linspace(1.1, 2.0, 200)   # 100ms gap at t=1.0
    t3 = np.linspace(2.1, 3.0, 200)   # 100ms gap at t=2.0
    tev = np.concatenate([t1, t2, t3])
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert len(gaps) == 2
    assert gaps[0][1] > 0.09
    assert gaps[1][1] > 0.09


def test_ooo_events_not_reported_as_gaps():
    """Negative dt (out-of-order event) is NOT reported as a gap (it is < threshold)."""
    tev = np.array([0.0, 0.001, 0.0009, 0.002, 0.003])  # backward jump at idx 2
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert gaps == []


def test_gap_exactly_at_threshold_not_reported():
    """Gap == threshold is NOT returned (strictly greater than)."""
    t1 = np.linspace(0.0, 1.0, 100)
    t2 = np.linspace(1.020, 2.0, 100)   # exactly 20ms gap
    tev = np.concatenate([t1, t2])
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert gaps == []


def test_gap_just_above_threshold_is_reported():
    """Gap of 21 ms (> 20 ms threshold) is returned."""
    t1 = np.linspace(0.0, 1.0, 100)
    t2 = np.linspace(1.021, 2.0, 100)
    tev = np.concatenate([t1, t2])
    gaps = hvc._find_pwm_gaps(tev, threshold_s=0.020)
    assert len(gaps) == 1


def test_empty_array_returns_empty():
    assert hvc._find_pwm_gaps(np.array([]), 0.020) == []


def test_single_element_returns_empty():
    assert hvc._find_pwm_gaps(np.array([1.0]), 0.020) == []
