"""Unit tests for hilbin_check.py — no VHDL simulator required."""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hilbin_check as hc


# ── Test fixture builder ──────────────────────────────────────────────────────

def _make_hilbin(
    tmp_path: Path,
    fpga_t: list[float],
    pwm_t: list[float],
    pwm_a: list[int] | None = None,
    pwm_b: list[int] | None = None,
    pwm_c: list[int] | None = None,
) -> Path:
    """Build a minimal valid .hilbin binary for testing."""
    if pwm_a is None:
        pwm_a = [3] * len(pwm_t)  # NPC_POS gate state
    if pwm_b is None:
        pwm_b = [3] * len(pwm_t)
    if pwm_c is None:
        pwm_c = [3] * len(pwm_t)

    meta_bytes = json.dumps({
        "version": 1, "date": "2026-01-01T00:00:00Z", "name": "test",
        "sample_count": len(fpga_t), "pwm_count": len(pwm_t),
        "raw": True, "clock_hz": 100_000_000,
    }).encode()
    pre = b"HILDATA\x01" + struct.pack("<I", len(meta_bytes)) + meta_bytes
    aligned = (len(pre) + 7) & ~7
    header = pre + b"\x00" * (aligned - len(pre))

    fpga_arr = np.zeros((len(fpga_t), 7), dtype="<f4")
    fpga_arr[:, 0] = np.array(fpga_t, dtype="<f4")

    pwm_bytes = b"".join(
        struct.pack("<f", t) + bytes([a, b, c, 0])
        for t, a, b, c in zip(pwm_t, pwm_a, pwm_b, pwm_c)
    )

    body = (
        struct.pack("<I", len(fpga_t)) + fpga_arr.tobytes()
        + struct.pack("<I", len(pwm_t)) + pwm_bytes
    )
    path = tmp_path / "test.hilbin"
    path.write_bytes(header + body)
    return path


# ── parse_hilbin ──────────────────────────────────────────────────────────────

def test_parse_hilbin_returns_correct_shapes(tmp_path):
    fpga_t = list(np.linspace(0.0, 1.0, 50))
    pwm_t = list(np.linspace(0.001, 1.0, 100))
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    meta, t_f, t_p, a, b, c = hc.parse_hilbin(path)
    assert t_f.shape == (50,)
    assert t_p.shape == (100,)
    assert a.shape == b.shape == c.shape == (100,)


def test_parse_hilbin_bad_magic_raises(tmp_path):
    bad = tmp_path / "bad.hilbin"
    bad.write_bytes(b"NOTDATA\x01" + b"\x00" * 20)
    with pytest.raises(ValueError, match="bad magic"):
        hc.parse_hilbin(bad)


def test_parse_hilbin_timestamps(tmp_path):
    fpga_t = [0.0, 0.1, 0.2]
    pwm_t = [0.0, 0.05, 0.1, 0.15]
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    _, t_f, t_p, _, _, _ = hc.parse_hilbin(path)
    np.testing.assert_allclose(t_f, fpga_t, atol=1e-6)
    np.testing.assert_allclose(t_p, pwm_t, atol=1e-6)


# ── check_file: clean capture ─────────────────────────────────────────────────

def test_clean_file_passes(tmp_path):
    """Continuous monotonic PWM stream with enough samples → ok."""
    fpga_t = list(np.linspace(0.0, 2.0, 200))
    pwm_t = list(np.linspace(0.001, 2.0, 400))
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    r = hc.check_file(path)
    assert r.ok, f"expected ok but errors={r.errors}"
    assert r.pwm_ooo_count == 0
    assert r.gaps == []


# ── check_file: critical gap ──────────────────────────────────────────────────

def test_critical_gap_detected(tmp_path):
    """A 200 ms gap at t=2.0 s is flagged as critical and fails the check."""
    fpga_t = list(np.linspace(0.0, 5.0, 500))
    # gap: 400 events from 0→2 s, then jump to 2.2 s, then 400 events to 5 s
    pwm_t = list(np.linspace(0.001, 2.0, 400)) + list(np.linspace(2.2, 5.0, 400))
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    r = hc.check_file(path)
    assert not r.ok
    assert any("gap" in e.lower() or "critical" in e.lower() for e in r.errors)
    assert r.largest_gap_ms > 150.0
    assert any(g["severity"] == "critical" for g in r.gaps)


# ── check_file: warning-level gap ────────────────────────────────────────────

def test_warning_gap_no_error(tmp_path):
    """A 15 ms gap (> warn 5 ms, < crit 50 ms) → warning but not error."""
    fpga_t = list(np.linspace(0.0, 2.0, 200))
    pwm_t = list(np.linspace(0.001, 1.0, 200)) + list(np.linspace(1.015, 2.0, 200))
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    r = hc.check_file(path)
    assert r.ok, f"unexpected errors: {r.errors}"
    assert any("gap" in w.lower() for w in r.warnings)
    assert r.largest_gap_ms > 10.0


# ── check_file: out-of-order events ──────────────────────────────────────────

def test_ooo_above_threshold_triggers_warning(tmp_path):
    """OOO fraction > 1 % produces a warning (not error)."""
    fpga_t = list(np.linspace(0.0, 1.0, 100))
    # produce > 1% OOO by swapping pairs
    pwm_t = list(np.linspace(0.001, 1.0, 200))
    # swap every 4th and 5th pair (creates backward dt)
    for i in range(3, len(pwm_t) - 1, 4):
        pwm_t[i], pwm_t[i + 1] = pwm_t[i + 1], pwm_t[i]
    path = _make_hilbin(tmp_path, fpga_t, pwm_t)
    r = hc.check_file(path)
    assert r.pwm_ooo_count > 0
    assert any("order" in w.lower() or "ooo" in w.lower() or "reorder" in w.lower()
               for w in r.warnings)


# ── check_file: insufficient data ────────────────────────────────────────────

def test_too_few_samples_errors(tmp_path):
    path = _make_hilbin(tmp_path, [0.0, 0.1], [0.0, 0.05, 0.1])  # only 2 FPGA samples
    r = hc.check_file(path)
    assert not r.ok
    assert any("few" in e.lower() for e in r.errors)
