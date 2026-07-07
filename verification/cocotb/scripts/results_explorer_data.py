#!/usr/bin/env python3
"""Data loading for the interactive HIL results explorer (Streamlit app).

Reads verification/results/*_campaign_*/ straight from disk. Never trusts
manifest.json -- a campaign's cases are its subdirectories, a case's runs
are its subdirectories (see docs/superpowers/specs/
2026-07-07-results-explorer-design.md and the related chapter_common.py
spec for why manifest.json is not a reliable source: l2_results/
l3_results have been observed empty even when metrics.json exists on
disk). No streamlit import here -- this module is plain stdlib so it can
be unit tested standalone.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "verification" / "results"

TIMESERIES_CSV_CANDIDATES = [
    "vf_vhdl_vs_c.csv",
    "top_pwm_replay_vs_c.csv",
    "sine_vhdl_vs_c.csv",
    "ref_vhdl_vs_c.csv",
    "fullstack_vs_top.csv",
]


@dataclass
class ChannelPair:
    suffix: str
    vhdl_col: str
    ref_col: str


def list_campaigns(results_root: Path = RESULTS_ROOT) -> list[Path]:
    if not results_root.is_dir():
        return []
    return sorted(p for p in results_root.iterdir() if p.is_dir() and "campaign" in p.name)


def list_cases(campaign_dir: Path) -> list[Path]:
    if not campaign_dir.is_dir():
        return []
    return sorted(
        p for p in campaign_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != "campaign_dashboard"
    )


def list_runs(case_dir: Path) -> list[Path]:
    if not case_dir.is_dir():
        return []
    return sorted(p for p in case_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def find_timeseries_csv(run_dir: Path) -> Path | None:
    for name in TIMESERIES_CSV_CANDIDATES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_header(csv_path: Path) -> list[str]:
    with csv_path.open(newline="") as f:
        return next(csv.reader(f))


def detect_channel_pairs(csv_path: Path) -> list[ChannelPair]:
    header = _read_header(csv_path)
    columns = set(header)
    pairs = []
    for col in header:
        if not col.startswith("vhdl_"):
            continue
        suffix = col[len("vhdl_"):]
        ref_col = f"ref_{suffix}"
        if ref_col not in columns:
            ref_col = f"c_{suffix}"
        if ref_col in columns:
            pairs.append(ChannelPair(suffix=suffix, vhdl_col=col, ref_col=ref_col))
    return pairs


def detect_time_column(csv_path: Path) -> tuple[str, float]:
    header = _read_header(csv_path)
    if "t_s" in header:
        return "t_s", 1.0
    return "t_us", 1e-6


def load_metrics(run_dir: Path) -> dict | None:
    path = run_dir / "metrics.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return doc.get("metrics", doc)
