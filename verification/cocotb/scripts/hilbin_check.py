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

GAP_WARN_S = 0.010   # > 10 ms → warning (5 ms is typical PWM period at 200 Hz)
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
        # NOTE: backward (OOO) events inflate the following forward dt, so a gap
        # flagged here that immediately follows an OOO cluster may be an artifact
        # of packet reordering rather than a real capture outage.  After recorder.go
        # sorts events at Stop(), new captures will not exhibit this false-positive.
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
            print(f"    ... and {len(r.gaps) - 5} more")
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
