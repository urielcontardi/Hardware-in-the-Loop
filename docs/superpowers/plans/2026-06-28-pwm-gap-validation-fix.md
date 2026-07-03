# PWM Gap Validation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix FPGA-vs-C-model divergence caused by gaps and out-of-order events in the PWM event stream, and add a diagnostic tool to detect capture quality issues before analysis.

**Architecture:** Three independent layers — (A) `hilbin_check.py` diagnostic reads .hilbin quality before analysis; (B) Go recorder sorts PWM events at Stop() time and increases the PWM channel buffer to prevent drops; (C) `hilbin_vs_c.py` detects PWM stream gaps during replay and reseeds the C model from the nearest FPGA telemetry sample instead of integrating at a stale gate state.

**Tech Stack:** Python 3.12, numpy, Go 1.22, pytest, standard Go testing

## Global Constraints

- Python interpreter: `uv run python` from `verification/cocotb/`
- Go module: `hil.local/daemon` (root `apps/hil-go/`)
- Go tests: `go test ./internal/record/... ./internal/pwmrecv/...` from `apps/hil-go/`
- Python tests: `uv run pytest scripts/tests/ -v` from `verification/cocotb/`
- GAP_RESEED_THRESHOLD_S = 0.020 (20 ms) — gaps shorter than this are minor OOO jitter, not FIFO overflow
- GAP_WARN_S = 0.005, GAP_CRIT_S = 0.050 for hilbin_check reporting
- `_CIMPrivateData.out` fields (ctypes struct, `im_reference_model.py:137`): `is_alpha`, `is_beta`, `fluxR_alpha`, `fluxR_beta`, `wm` — these map 1:1 to the fpga dict keys `ia`, `ib`, `flux_a`, `flux_b`, `speed`
- Never change `pyproject.toml` testpaths — the cocotb tests in `tests/` need their own runner

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| CREATE | `verification/cocotb/scripts/hilbin_check.py` | Standalone diagnostic CLI for .hilbin quality |
| CREATE | `verification/cocotb/scripts/tests/__init__.py` | Makes scripts/tests a package |
| CREATE | `verification/cocotb/scripts/tests/test_hilbin_check.py` | pytest unit tests for hilbin_check |
| CREATE | `verification/cocotb/scripts/tests/test_pwm_gap_replay.py` | pytest unit tests for gap detection helper |
| MODIFY | `apps/hil-go/internal/pwmrecv/pwmrecv.go:52` | Channel 128 → 4096 |
| MODIFY | `apps/hil-go/internal/record/recorder.go` | Add `"sort"` import; sort pwmEvents in Stop() |
| MODIFY | `apps/hil-go/internal/record/recorder_test.go` | Add TestRecorderSortsPWMEvents |
| MODIFY | `verification/cocotb/scripts/hilbin_vs_c.py` | Add gap helper, reseed logic, PWM sort in run_one |

---

### Task 1: hilbin_check.py — Capture diagnostic tool

**Files:**
- Create: `verification/cocotb/scripts/hilbin_check.py`
- Create: `verification/cocotb/scripts/tests/__init__.py`
- Create: `verification/cocotb/scripts/tests/test_hilbin_check.py`

**Interfaces:**
- Produces: `check_file(path: Path) -> CheckResult` (dataclass with `.ok`, `.gaps`, `.pwm_ooo_count`, `.errors`, `.warnings`)
- Produces: `parse_hilbin(path: Path) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]` — `(meta, t_fpga, t_pwm, a_pwm, b_pwm, c_pwm)`
- Task 3 will import `parse_hilbin` for reuse in tests

- [ ] **Step 1: Create `verification/cocotb/scripts/tests/__init__.py`** (empty file)

```bash
touch verification/cocotb/scripts/tests/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_hilbin_check.py`:

```python
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
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_hilbin_check.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'hilbin_check'`

- [ ] **Step 4: Create `verification/cocotb/scripts/hilbin_check.py`**

```python
#!/usr/bin/env python3
"""hilbin_check.py — quality diagnostic for .hilbin capture files.

Detects gaps and out-of-order events in the PWM stream before analysis.
Exit 0 = all files OK; exit 1 = at least one critical issue found.

Usage (from verification/cocotb/):
    uv run python scripts/hilbin_check.py path/to/file.hilbin
    uv run python scripts/hilbin_check.py --all
    uv run python scripts/hilbin_check.py file.hilbin --json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RUNS_DIR = Path(__file__).resolve().parents[3] / "apps" / "hil-go" / "runs"

_PWM_DTYPE = np.dtype([("t", "<f4"), ("a", "u1"), ("b", "u1"), ("c", "u1"), ("pad", "u1")])
_SAMPLE_FLOATS = 7  # t, ia, ib, flux_a, flux_b, speed, pad

GAP_WARN_S = 0.005   # > 5 ms → warning
GAP_CRIT_S = 0.050   # > 50 ms → critical (C model will diverge)
OOO_WARN_FRAC = 0.01 # > 1 % out-of-order events → warning


@dataclass
class CheckResult:
    path: str
    ok: bool
    fpga_samples: int
    pwm_events: int
    fpga_duration_s: float
    pwm_duration_s: float
    pwm_ooo_count: int
    pwm_ooo_frac: float
    gaps: list[dict] = field(default_factory=list)
    largest_gap_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "ok": self.ok,
            "fpga_samples": self.fpga_samples,
            "pwm_events": self.pwm_events,
            "fpga_duration_s": round(self.fpga_duration_s, 4),
            "pwm_duration_s": round(self.pwm_duration_s, 4),
            "pwm_ooo_count": self.pwm_ooo_count,
            "pwm_ooo_frac": round(self.pwm_ooo_frac, 5),
            "gaps": self.gaps,
            "largest_gap_ms": round(self.largest_gap_ms, 2),
            "warnings": self.warnings,
            "errors": self.errors,
        }


def parse_hilbin(path: Path):
    """Parse a .hilbin file.

    Returns:
        (meta, t_fpga, t_pwm, a_pwm, b_pwm, c_pwm)
        All time arrays are float64, gate arrays are int.

    Raises:
        ValueError: if magic bytes are wrong
    """
    data = Path(path).read_bytes()
    if data[:7] != b"HILDATA":
        raise ValueError(f"{path}: bad magic")
    meta_len = struct.unpack_from("<I", data, 8)[0]
    meta = json.loads(data[12:12 + meta_len])
    pos = (12 + meta_len + 7) & ~7

    sample_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if sample_count:
        raw = np.frombuffer(
            data, dtype="<f4", count=sample_count * _SAMPLE_FLOATS, offset=pos
        ).reshape(-1, _SAMPLE_FLOATS)
        t_fpga = raw[:, 0].astype(np.float64)
    else:
        t_fpga = np.array([], dtype=np.float64)
    pos += sample_count * _SAMPLE_FLOATS * 4

    pwm_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if pwm_count:
        ev = np.frombuffer(data, dtype=_PWM_DTYPE, count=pwm_count, offset=pos)
        t_pwm = ev["t"].astype(np.float64)
        a_pwm = ev["a"].astype(int)
        b_pwm = ev["b"].astype(int)
        c_pwm = ev["c"].astype(int)
    else:
        t_pwm = np.array([], dtype=np.float64)
        a_pwm = b_pwm = c_pwm = np.array([], dtype=int)

    return meta, t_fpga, t_pwm, a_pwm, b_pwm, c_pwm


def check_file(path: Path) -> CheckResult:
    """Run all quality checks on a single .hilbin file."""
    warnings: list[str] = []
    errors: list[str] = []

    try:
        meta, t_fpga, t_pwm, _, _, _ = parse_hilbin(path)
    except Exception as exc:
        return CheckResult(
            path=str(path), ok=False,
            fpga_samples=0, pwm_events=0,
            fpga_duration_s=0.0, pwm_duration_s=0.0,
            pwm_ooo_count=0, pwm_ooo_frac=0.0,
            errors=[f"parse error: {exc}"],
        )

    fpga_samples = len(t_fpga)
    pwm_events = len(t_pwm)
    fpga_duration_s = float(t_fpga[-1] - t_fpga[0]) if fpga_samples > 1 else 0.0
    pwm_duration_s = float(t_pwm[-1] - t_pwm[0]) if pwm_events > 1 else 0.0

    if fpga_samples < 8:
        errors.append(f"too few FPGA samples ({fpga_samples})")
    if pwm_events < 4:
        errors.append(f"too few PWM events ({pwm_events})")

    ooo_count = 0
    ooo_frac = 0.0
    gaps: list[dict] = []
    largest_gap_ms = 0.0

    if pwm_events > 1:
        dt = np.diff(t_pwm)

        # Out-of-order events (dt <= 0)
        ooo_mask = dt <= 0
        ooo_count = int(ooo_mask.sum())
        ooo_frac = ooo_count / len(dt)
        if ooo_frac > OOO_WARN_FRAC:
            warnings.append(
                f"{ooo_count} out-of-order PWM timestamps "
                f"({ooo_frac * 100:.1f}%) — likely UDP packet reordering; "
                "fix: recorder.go Stop() now sorts pwmEvents"
            )

        # Gaps in the forward-going events
        gap_mask = dt > GAP_WARN_S
        for gi in np.where(gap_mask)[0]:
            dt_ms = float(dt[gi]) * 1000.0
            severity = "critical" if dt[gi] > GAP_CRIT_S else "warning"
            gaps.append({
                "t_s": round(float(t_pwm[gi]), 4),
                "dt_ms": round(dt_ms, 2),
                "severity": severity,
            })

        if gaps:
            largest_gap_ms = max(g["dt_ms"] for g in gaps)
            crit = [g for g in gaps if g["severity"] == "critical"]
            if crit:
                errors.append(
                    f"{len(crit)} critical gap(s) in PWM stream "
                    f"(largest {largest_gap_ms:.1f} ms) — C model will diverge; "
                    "hilbin_vs_c uses mid-window reseed to mitigate"
                )
            else:
                warnings.append(
                    f"{len(gaps)} gap(s) in PWM stream "
                    f"(largest {largest_gap_ms:.1f} ms)"
                )

    return CheckResult(
        path=str(path), ok=len(errors) == 0,
        fpga_samples=fpga_samples, pwm_events=pwm_events,
        fpga_duration_s=fpga_duration_s, pwm_duration_s=pwm_duration_s,
        pwm_ooo_count=ooo_count, pwm_ooo_frac=ooo_frac,
        gaps=gaps, largest_gap_ms=largest_gap_ms,
        warnings=warnings, errors=errors,
    )


def _print_result(r: CheckResult) -> None:
    status = "OK  " if r.ok else "FAIL"
    print(f"\n[{status}] {Path(r.path).name}")
    print(f"  FPGA : {r.fpga_samples:>8} samples   {r.fpga_duration_s:.3f} s")
    print(f"  PWM  : {r.pwm_events:>8} events    {r.pwm_duration_s:.3f} s  "
          f"OOO={r.pwm_ooo_count} ({r.pwm_ooo_frac * 100:.2f}%)")
    if r.gaps:
        print(f"  Gaps : {len(r.gaps)} (largest {r.largest_gap_ms:.1f} ms)")
        for g in r.gaps[:5]:
            print(f"    t={g['t_s']:.3f} s   {g['dt_ms']:.1f} ms   [{g['severity']}]")
        if len(r.gaps) > 5:
            print(f"    … and {len(r.gaps) - 5} more")
    for w in r.warnings:
        print(f"  WARN : {w}")
    for e in r.errors:
        print(f"  ERR  : {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Quality check for .hilbin capture files.")
    ap.add_argument("capture", nargs="?", help="path to a .hilbin file")
    ap.add_argument("--all", action="store_true",
                    help=f"check all .hilbin files in {RUNS_DIR}")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="output results as JSON array")
    args = ap.parse_args()

    if args.all:
        files = sorted(RUNS_DIR.glob("*.hilbin"))
        if not files:
            print(f"No .hilbin files found in {RUNS_DIR}")
            sys.exit(0)
    elif args.capture:
        files = [Path(args.capture)]
    else:
        ap.error("pass a .hilbin path or --all")

    results = [check_file(f) for f in files]

    if args.as_json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        for r in results:
            _print_result(r)
        n_fail = sum(1 for r in results if not r.ok)
        print(f"\n{'─' * 60}")
        print(f"  {len(results)} file(s) checked  •  {n_fail} fail(s)")

    sys.exit(1 if any(not r.ok for r in results) else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_hilbin_check.py -v
```

Expected output:
```
PASSED test_parse_hilbin_returns_correct_shapes
PASSED test_parse_hilbin_bad_magic_raises
PASSED test_parse_hilbin_timestamps
PASSED test_clean_file_passes
PASSED test_critical_gap_detected
PASSED test_warning_gap_no_error
PASSED test_ooo_above_threshold_triggers_warning
PASSED test_too_few_samples_errors
8 passed
```

- [ ] **Step 6: Smoke test on a real capture**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/hilbin_check.py --all
```

Expected: each file prints `[OK  ]` or `[FAIL]` with gap/OOO details.

- [ ] **Step 7: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/hilbin_check.py \
        verification/cocotb/scripts/tests/__init__.py \
        verification/cocotb/scripts/tests/test_hilbin_check.py
git commit -m "feat(validation): add hilbin_check.py diagnostic for PWM stream quality"
```

---

### Task 2: Go recorder — sort PWM events and increase channel buffer

**Files:**
- Modify: `apps/hil-go/internal/pwmrecv/pwmrecv.go:52`
- Modify: `apps/hil-go/internal/record/recorder.go:3-17` (imports) and `recorder.go:168-180` (Stop loop)
- Modify: `apps/hil-go/internal/record/recorder_test.go` (append new test)

**Interfaces:**
- Consumes: existing `pwmrecv.Batch`, `record.Recorder.Stop()`
- Produces: `.hilbin` files whose PWM section has events sorted by ascending timestamp

- [ ] **Step 1: Write the failing Go test**

Append to `apps/hil-go/internal/record/recorder_test.go`:

```go
func TestRecorderSortsPWMEventsByTimestamp(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	if _, err := r.Start("sort_test"); err != nil {
		t.Fatal(err)
	}
	// Establish epoch via one FPGA sample
	r.Submit([]frame.Sample{{TCycles: 10, Epoch: 1, Ia: 1}})
	// Submit PWM events out of order (simulates UDP packet reordering):
	// second batch arrives first with a later timestamp, then first batch catches up.
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 200, Epoch: 1, A: 1, B: 1, C: 1}})
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 100, Epoch: 1, A: 2, B: 2, C: 2}})
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 300, Epoch: 1, A: 3, B: 3, C: 3}})
	if err := r.Stop(); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, "sorted.hilbin")
	if copied, err := r.CopyLatest(dst, nil); err != nil || !copied {
		t.Fatalf("CopyLatest: copied=%v err=%v", copied, err)
	}
	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}

	// Skip header and FPGA samples to reach PWM section
	metaLen := int(binary.LittleEndian.Uint32(data[8:12]))
	off := (12 + metaLen + 7) &^ 7
	fpgaCount := binary.LittleEndian.Uint32(data[off:])
	off += 4 + int(fpgaCount)*sampleBytes

	pwmCount := binary.LittleEndian.Uint32(data[off:])
	if pwmCount != 3 {
		t.Fatalf("pwm count=%d want 3", pwmCount)
	}
	off += 4

	// Each PWM record: 4 bytes f32 time + 4 bytes (a,b,c,pad)
	const pwmRecBytes = 8
	readPWM := func(i int) (float32, uint8, uint8, uint8) {
		base := off + i*pwmRecBytes
		ts := math.Float32frombits(binary.LittleEndian.Uint32(data[base:]))
		return ts, data[base+4], data[base+5], data[base+6]
	}

	t0, a0, _, _ := readPWM(0)
	t1, a1, _, _ := readPWM(1)
	t2, a2, _, _ := readPWM(2)

	// After sort: order by TCycles → 100 (A=2), 200 (A=1), 300 (A=3)
	if !(t0 < t1 && t1 < t2) {
		t.Fatalf("PWM events not sorted by time: %v %v %v", t0, t1, t2)
	}
	if a0 != 2 {
		t.Fatalf("first event (TCycles=100) should have A=2, got %d", a0)
	}
	if a1 != 1 {
		t.Fatalf("second event (TCycles=200) should have A=1, got %d", a1)
	}
	if a2 != 3 {
		t.Fatalf("third event (TCycles=300) should have A=3, got %d", a2)
	}
}
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/apps/hil-go
go test ./internal/record/... -run TestRecorderSortsPWMEventsByTimestamp -v
```

Expected: `FAIL — PWM events not sorted by time` (currently written in arrival order: 200, 100, 300)

- [ ] **Step 3: Increase pwmrecv channel capacity**

In `apps/hil-go/internal/pwmrecv/pwmrecv.go`, change line 52:

```go
// Before:
return &Receiver{port: port, C: make(chan Batch, 128), quit: make(chan struct{})}

// After:
return &Receiver{port: port, C: make(chan Batch, 4096), quit: make(chan struct{})}
```

- [ ] **Step 4: Add `"sort"` import to recorder.go**

In `apps/hil-go/internal/record/recorder.go`, change the import block:

```go
// Before:
import (
	"encoding/binary"
	"encoding/json"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
)

// After:
import (
	"encoding/binary"
	"encoding/json"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
)
```

- [ ] **Step 5: Add sort call in Stop() before writing pwmEvents**

In `apps/hil-go/internal/record/recorder.go`, find the loop in `Stop()` that writes PWM events (around line 174):

```go
// Before:
	for _, ev := range r.pwmEvents {
		var raw [8]byte
		binary.LittleEndian.PutUint32(raw[:4], math.Float32bits(ev.t))
		raw[4], raw[5], raw[6] = ev.a, ev.b, ev.c
		if _, err := r.file.Write(raw[:]); err != nil {
			return err
		}
	}

// After:
	sort.SliceStable(r.pwmEvents, func(i, j int) bool {
		return r.pwmEvents[i].t < r.pwmEvents[j].t
	})
	for _, ev := range r.pwmEvents {
		var raw [8]byte
		binary.LittleEndian.PutUint32(raw[:4], math.Float32bits(ev.t))
		raw[4], raw[5], raw[6] = ev.a, ev.b, ev.c
		if _, err := r.file.Write(raw[:]); err != nil {
			return err
		}
	}
```

- [ ] **Step 6: Run all Go tests**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/apps/hil-go
go test ./internal/record/... ./internal/pwmrecv/... -v
```

Expected: all existing tests + `TestRecorderSortsPWMEventsByTimestamp` PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add apps/hil-go/internal/pwmrecv/pwmrecv.go \
        apps/hil-go/internal/record/recorder.go \
        apps/hil-go/internal/record/recorder_test.go
git commit -m "fix(recorder): sort PWM events at Stop() and increase pwmrecv channel to 4096"
```

---

### Task 3: Python gap-aware replay in hilbin_vs_c.py

**Files:**
- Modify: `verification/cocotb/scripts/hilbin_vs_c.py`
- Create: `verification/cocotb/scripts/tests/test_pwm_gap_replay.py`

**Interfaces:**
- Consumes: existing `run_c_model_seeded`, `_seed_at`, `_win`, `_metrics` from hilbin_vs_c.py
- Produces:
  - `_find_pwm_gaps(tev: np.ndarray, threshold_s: float) -> list[tuple[int, float]]`
    returns `[(event_idx_before_gap, gap_duration_s), ...]`
  - `run_c_model_seeded(pwm, vdc, params, t_start, t_end, seed, fpga=None)`
    return dict gains two new keys: `"gap_count": int`, `"gap_total_s": float`

- [ ] **Step 1: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_pwm_gap_replay.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_pwm_gap_replay.py -v 2>&1 | head -10
```

Expected: `AttributeError: module 'hilbin_vs_c' has no attribute '_find_pwm_gaps'`

- [ ] **Step 3: Add `GAP_RESEED_THRESHOLD_S` constant to hilbin_vs_c.py**

In `verification/cocotb/scripts/hilbin_vs_c.py`, find the imports block (around line 34, after `import numpy as np`). Add after the existing imports from `fpga_vs_c`:

```python
# ── Gap reseed threshold ──────────────────────────────────────────────────────
# PWM gaps shorter than this are minor UDP jitter (handled by OOO sort).
# Gaps longer than this indicate FIFO overflow; the C model is reseeded from
# FPGA telemetry at the gap boundary to prevent divergence.
GAP_RESEED_THRESHOLD_S = 0.020   # 20 ms
```

- [ ] **Step 4: Add `_find_pwm_gaps` helper function to hilbin_vs_c.py**

Add immediately after the `GAP_RESEED_THRESHOLD_S` constant (before `run_c_model_seeded`):

```python
def _find_pwm_gaps(tev: np.ndarray, threshold_s: float) -> list[tuple[int, float]]:
    """Return (index_before_gap, gap_duration_s) for each gap > threshold_s.

    Only positive dt values exceeding the threshold are returned; out-of-order
    events (dt <= 0) are ignored here and handled by the upstream sort step.
    """
    if len(tev) < 2:
        return []
    dt = np.diff(tev.astype(np.float64))
    mask = dt > threshold_s
    return [(int(i), float(dt[i])) for i in np.where(mask)[0]]
```

- [ ] **Step 5: Run gap tests — verify they pass**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_pwm_gap_replay.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Modify `run_c_model_seeded` to accept `fpga` and reseed on gaps**

In `verification/cocotb/scripts/hilbin_vs_c.py`, replace the entire `run_c_model_seeded` function (lines 146–190):

```python
def run_c_model_seeded(pwm, vdc, params, t_start, t_end, seed, fpga=None):
    """Replay [t_start, t_end] through the C model, seeding from FPGA at t_start.

    When a gap > GAP_RESEED_THRESHOLD_S is detected in the PWM stream the C
    model is reseeded from the nearest FPGA telemetry sample instead of
    integrating at the stale gate state.  This prevents the current explosion
    that would otherwise occur during a FIFO overflow or UDP packet loss window.

    If fpga is None the old behaviour (no reseed) is preserved for callers that
    do not have FPGA telemetry available.

    Return dict includes:
        gap_count  — number of gaps reseeded
        gap_total_s — cumulative duration of all gaps [s]
    """
    model = InductionMotorReferenceModel(params=params, backend="c")
    priv = ctypes.cast(model._impl._model.priv, ctypes.POINTER(_CIMPrivateData)).contents

    def _apply_seed(s: dict) -> None:
        priv.out.is_alpha   = float(s["ia"])
        priv.out.is_beta    = float(s["ib"])
        priv.out.fluxR_alpha = float(s["flux_a"])
        priv.out.fluxR_beta  = float(s["flux_b"])
        priv.out.wm         = float(s["speed"])

    _apply_seed(seed)

    ts = L4.SOLVER_TS
    vhalf = vdc / 2.0
    store_every = max(1, round((1.0 / 10_000.0) / ts))
    tev = pwm["t"]
    ga, gb, gc = pwm["a"], pwm["b"], pwm["c"]
    j0 = max(0, int(np.searchsorted(tev, t_start)) - 1)

    T, IA, IB, FA, FB, SP = [], [], [], [], [], []
    t = float(tev[j0])
    k = 0
    gap_count = 0
    gap_total_s = 0.0

    for j in range(j0, len(tev) - 1):
        if t > t_end:
            break
        dt = float(tev[j + 1] - tev[j])
        n = int(round(dt / ts))
        if n <= 0 or n > 5_000_000:
            continue

        if dt > GAP_RESEED_THRESHOLD_S and fpga is not None:
            # Reseed from FPGA telemetry at the gap boundary, then jump the
            # simulation clock to the end of the gap so the next PWM event
            # applies at the correct time.
            _apply_seed(_seed_at(fpga, float(tev[j + 1])))
            t = float(tev[j + 1])
            gap_count += 1
            gap_total_s += dt
            continue

        vva = L4._gate_to_v(ga[j], vhalf)
        vvb = L4._gate_to_v(gb[j], vhalf)
        vvc = L4._gate_to_v(gc[j], vhalf)
        for _ in range(n):
            st = model.step(vva, vvb, vvc, 0.0)
            if k % store_every == 0 and t >= t_start:
                T.append(t); IA.append(st.i_alpha); IB.append(st.i_beta)
                FA.append(st.flux_alpha); FB.append(st.flux_beta)
                SP.append(st.speed_mech)
            t += ts
            k += 1

    return {
        "t": np.array(T), "ia": np.array(IA), "ib": np.array(IB),
        "flux_a": np.array(FA), "flux_b": np.array(FB), "speed": np.array(SP),
        "backend": model.backend_name,
        "gap_count": gap_count,
        "gap_total_s": round(gap_total_s, 4),
    }
```

- [ ] **Step 7: Sort PWM events and pass `fpga` in `run_one`**

In `verification/cocotb/scripts/hilbin_vs_c.py`, find `run_one` (around line 278). Apply these two changes:

**7a — sort PWM events right after `_rezero`** (handles old files before Go sort fix):

```python
# Before:
    fpga = _clip_fpga(fpga)
    pwm = _rezero(pwm)
    seg_dur = float(fpga["t"][-1]) if fpga["t"].size else 0.0

# After:
    fpga = _clip_fpga(fpga)
    pwm = _rezero(pwm)
    if pwm["t"].size > 1:
        _ord = np.argsort(pwm["t"], kind="stable")
        pwm = {k: v[_ord] for k, v in pwm.items()}
    seg_dur = float(fpga["t"][-1]) if fpga["t"].size else 0.0
```

**7b — pass `fpga=fpga` to `run_c_model_seeded`** (the call is ~20 lines into `run_one`, inside the `for label, (ta, tb)` loop):

```python
# Before:
        cmod = run_c_model_seeded(pwm, vdc, params, ta, tb, seed)

# After:
        cmod = run_c_model_seeded(pwm, vdc, params, ta, tb, seed, fpga=fpga)
```

**7c — add gap info to per-window metrics output** (in the `print` line just after `run_c_model_seeded`):

```python
# Before:
        print(f"  [{label} {ta:.2f}-{tb:.2f}s] iα NRMSE={m.get('ia_nrmse')}%  "
              f"lag={lag*1e3:+.2f}ms  backend={cmod['backend']}")

# After:
        gaps_str = (f"  gaps={cmod['gap_count']}({cmod['gap_total_s']:.2f}s)"
                    if cmod["gap_count"] else "")
        print(f"  [{label} {ta:.2f}-{tb:.2f}s] iα NRMSE={m.get('ia_nrmse')}%  "
              f"lag={lag*1e3:+.2f}ms  backend={cmod['backend']}{gaps_str}")
```

**7d — store gap info in per-window metrics dict** (just after `out[label] = m`):

```python
# Before:
        out[label] = m

# After:
        m["pwm_gaps"] = {
            "count": cmod["gap_count"],
            "total_s": cmod["gap_total_s"],
        }
        out[label] = m
```

- [ ] **Step 8: Run all Python unit tests**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/ -v
```

Expected: all tests from Task 1 + Task 3 PASS (≥ 15 tests).

- [ ] **Step 9: Smoke test on a real capture**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/hilbin_vs_c.py \
  ../../apps/hil-go/runs/capture_20260628_142046.395.hilbin --window 2.0
```

Expected: regime window reports `gaps=1(1.41s)` with metrics JSON showing `"pwm_gaps": {"count": 1, "total_s": 1.41}`, and the regime PNG shows FPGA and C model overlapping without divergence.

- [ ] **Step 10: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/hilbin_vs_c.py \
        verification/cocotb/scripts/tests/test_pwm_gap_replay.py
git commit -m "fix(validation): gap-aware C model reseed in hilbin_vs_c — prevents divergence at PWM stream gaps"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Diagnostic shows gaps > 5ms as warn, > 50ms as crit | Task 1 `check_file`, tests `test_warning_gap_no_error`, `test_critical_gap_detected` |
| Diagnostic shows OOO count and fraction | Task 1 `check_file`, test `test_ooo_above_threshold_triggers_warning` |
| Diagnostic exits non-zero on critical issues | Task 1 `main()` `sys.exit(1 if any...)` |
| Go channel 128 → 4096 | Task 2 Step 3 |
| Go sort PWM events in Stop() | Task 2 Steps 4–5, test `TestRecorderSortsPWMEventsByTimestamp` |
| Python PWM sort for old files | Task 3 Step 7a |
| Gap reseed: 20ms threshold | Task 3 `GAP_RESEED_THRESHOLD_S`, `_find_pwm_gaps` |
| Gap reseed: jump sim clock to end of gap | Task 3 Step 6 `t = float(tev[j + 1])` |
| Gap reseed: seed from FPGA telemetry at gap end | Task 3 Step 6 `_apply_seed(_seed_at(fpga, float(tev[j+1])))` |
| gap_count / gap_total_s in metrics.json | Task 3 Steps 7c–7d |

**Placeholder scan:** None found.

**Type consistency:**
- `_find_pwm_gaps` returns `list[tuple[int, float]]` — used only in tests (no cross-task dependency needed at runtime; gap detection is inline in `run_c_model_seeded`)
- `run_c_model_seeded` signature change: `fpga=None` default — all existing callers in `hilbin_vs_c.py` only call it from `run_one`; the `fpga` kwarg is added in Task 3 Step 7b
- `_apply_seed` inner function uses the same ctypes fields as the original seed code: `is_alpha`, `is_beta`, `fluxR_alpha`, `fluxR_beta`, `wm` — matches `_CIMPrivateData._CIMStates` definition in `im_reference_model.py:137`
