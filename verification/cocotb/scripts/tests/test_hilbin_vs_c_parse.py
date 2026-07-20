"""Unit tests for hilbin_vs_c.parse_hilbin.

Regression coverage for a byte-offset bug: adding the v1/v2 PWM dtype switch
dropped the `pos += 4` after reading pwm_count, so the event array was read
starting 4 bytes early (right on top of the count field itself). Every field
decoded as garbage (denormalized floats near 1e-39), for both v1 and v2 files,
silently -- np.frombuffer never raises on a misaligned-but-in-bounds offset.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hilbin_vs_c as hvc


def _make_hilbin_v1(tmp_path: Path, fpga_t, pwm_t, pwm_a=None, pwm_b=None, pwm_c=None,
                    clock_hz=100_000_000):
    pwm_a = pwm_a or [3] * len(pwm_t)
    pwm_b = pwm_b or [3] * len(pwm_t)
    pwm_c = pwm_c or [3] * len(pwm_t)
    meta_bytes = json.dumps({
        "version": 1, "date": "2026-01-01T00:00:00Z", "name": "test",
        "sample_count": len(fpga_t), "pwm_count": len(pwm_t),
        "raw": True, "clock_hz": clock_hz,
    }).encode()
    pre = b"HILDATA\x01" + struct.pack("<I", len(meta_bytes)) + meta_bytes
    header = pre + b"\x00" * (((len(pre) + 7) & ~7) - len(pre))
    fpga_arr = np.zeros((len(fpga_t), 7), dtype="<f4")
    fpga_arr[:, 0] = np.array(fpga_t, dtype="<f4")
    pwm_bytes = b"".join(
        struct.pack("<f", t) + bytes([a, b, c, 0])
        for t, a, b, c in zip(pwm_t, pwm_a, pwm_b, pwm_c)
    )
    body = (struct.pack("<I", len(fpga_t)) + fpga_arr.tobytes()
            + struct.pack("<I", len(pwm_t)) + pwm_bytes)
    path = tmp_path / "test_v1.hilbin"
    path.write_bytes(header + body)
    return path


def _make_hilbin_v2(tmp_path: Path, fpga_t, pwm_cycles, pwm_a=None, pwm_b=None, pwm_c=None,
                    clock_hz=100_000_000):
    pwm_a = pwm_a or [3] * len(pwm_cycles)
    pwm_b = pwm_b or [3] * len(pwm_cycles)
    pwm_c = pwm_c or [3] * len(pwm_cycles)
    meta_bytes = json.dumps({
        "version": 2, "date": "2026-01-01T00:00:00Z", "name": "test",
        "sample_count": len(fpga_t), "pwm_count": len(pwm_cycles),
        "raw": True, "clock_hz": clock_hz,
    }).encode()
    pre = b"HILDATA\x02" + struct.pack("<I", len(meta_bytes)) + meta_bytes
    header = pre + b"\x00" * (((len(pre) + 7) & ~7) - len(pre))
    fpga_arr = np.zeros((len(fpga_t), 7), dtype="<f4")
    fpga_arr[:, 0] = np.array(fpga_t, dtype="<f4")
    pwm_bytes = b"".join(
        struct.pack("<I", c) + bytes([a, b, cc, 0])
        for c, a, b, cc in zip(pwm_cycles, pwm_a, pwm_b, pwm_c)
    )
    body = (struct.pack("<I", len(fpga_t)) + fpga_arr.tobytes()
            + struct.pack("<I", len(pwm_cycles)) + pwm_bytes)
    path = tmp_path / "test_v2.hilbin"
    path.write_bytes(header + body)
    return path


def test_v1_pwm_timestamps_decode_correctly(tmp_path):
    fpga_t = list(np.linspace(0.0, 2.0, 50))
    pwm_t = [0.001, 0.5, 1.0, 1.999]
    path = _make_hilbin_v1(tmp_path, fpga_t, pwm_t)

    _, fpga, pwm = hvc.parse_hilbin(path)

    np.testing.assert_allclose(pwm["t"], pwm_t, atol=1e-5)
    assert fpga["t"].max() > 1.9


def test_v1_pwm_gate_levels_decode_correctly(tmp_path):
    """A byte-offset error would misalign a,b,c too, not just t."""
    fpga_t = list(np.linspace(0.0, 1.0, 20))
    pwm_t = [0.1, 0.2, 0.3]
    path = _make_hilbin_v1(tmp_path, fpga_t, pwm_t, pwm_a=[3, 2, 6], pwm_b=[4, 12, 3], pwm_c=[6, 6, 4])

    _, _, pwm = hvc.parse_hilbin(path)

    np.testing.assert_array_equal(pwm["a"], [3, 2, 6])
    np.testing.assert_array_equal(pwm["b"], [4, 12, 3])
    np.testing.assert_array_equal(pwm["c"], [6, 6, 4])


def test_v2_pwm_cycles_decode_to_correct_seconds(tmp_path):
    fpga_t = list(np.linspace(0.0, 2.0, 50))
    clock_hz = 100_000_000
    cycles = [10_000, 50_000_000, 100_000_000, 199_900_000]
    path = _make_hilbin_v2(tmp_path, fpga_t, cycles, clock_hz=clock_hz)

    _, _, pwm = hvc.parse_hilbin(path)

    expected = np.array(cycles, dtype=float) / clock_hz
    np.testing.assert_allclose(pwm["t"], expected, atol=1e-9)


def test_v2_pwm_gate_levels_decode_correctly(tmp_path):
    fpga_t = list(np.linspace(0.0, 1.0, 20))
    cycles = [1_000, 2_000, 3_000]
    path = _make_hilbin_v2(tmp_path, fpga_t, cycles, pwm_a=[3, 2, 6], pwm_b=[4, 12, 3], pwm_c=[6, 6, 4])

    _, _, pwm = hvc.parse_hilbin(path)

    np.testing.assert_array_equal(pwm["a"], [3, 2, 6])
    np.testing.assert_array_equal(pwm["b"], [4, 12, 3])
    np.testing.assert_array_equal(pwm["c"], [6, 6, 4])


def test_pwm_timestamps_are_not_denormalized_garbage(tmp_path):
    """A 4-byte offset error reads a,b,c/pad bytes as part of the next record's
    float, producing values in the 1e-30..1e-45 (denormal) range -- physically
    impossible for a real timestamp. Guards against that class of bug generally,
    not just the exact offset that caused it once."""
    fpga_t = list(np.linspace(0.0, 2.0, 50))
    pwm_t = [0.001 * i for i in range(1, 30)]
    path = _make_hilbin_v1(tmp_path, fpga_t, pwm_t)

    _, _, pwm = hvc.parse_hilbin(path)

    assert pwm["t"].max() > 1e-6, f"timestamps look denormalized: {pwm['t'][:5]}"
    assert pwm["t"].max() < fpga_t[-1] * 2
