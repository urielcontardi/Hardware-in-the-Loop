"""Testes de compute_transient_metrics — funcao pura, sem simulador."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from models.transient_metrics import compute_transient_metrics


def test_returns_zero_when_no_step_in_window():
    t = [0.0, 0.1, 0.2]
    speed = [50.0, 50.0, 50.0]
    i_alpha = [0.0, 0.0, 0.0]
    i_beta = [0.0, 0.0, 0.0]
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=1.0)
    assert result["speed_before_step_rad_s"] == 50.0
    assert result["speed_peak_deviation_rad_s"] == 0.0
    assert result["current_peak_a"] == 0.0
    assert result["recovery_time_s"] is None


def test_detects_peak_deviation_current_peak_and_recovery_time():
    t = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    speed = [100.0] * 6 + [70.0, 85.0, 95.0, 99.0, 100.0]
    i_alpha = [0.0] * 6 + [50.0, 30.0, 10.0, 2.0, 0.0]
    i_beta = [0.0] * 11
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=0.6)
    assert result["speed_before_step_rad_s"] == 100.0
    assert result["speed_peak_deviation_rad_s"] == pytest.approx(30.0)
    assert result["current_peak_a"] == pytest.approx(50.0)
    assert result["recovery_time_s"] == pytest.approx(0.2, abs=1e-9)


def test_recovery_time_none_when_it_never_settles():
    t = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    speed = [100.0] * 6 + [70.0, 72.0, 10.0]
    i_alpha = [0.0] * 9
    i_beta = [0.0] * 9
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=0.6)
    assert result["speed_peak_deviation_rad_s"] == pytest.approx(90.0)
    assert result["recovery_time_s"] is None
