#!/usr/bin/env python3
"""Shared data loading for the results-chapter table/figure generators.

Reads manifest.json plus per-case metrics.json/CSV straight from disk on
every call. Never trusts the `status` field or the `l2_results`/
`l3_results` keys in manifest.json -- those have been observed stale or
incomplete on campaign_03 (A2/A3/A4/A6/A7 show `l2_results: {}` even though
`metrics.json` exists on disk). File existence on disk is the only source
of truth: each case's L2/L3 directory is found by globbing inside the
case's own directory, not by reading manifest pointers.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "verification" / "results"

GRUPO_A_IDS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]

L2_CSV_NAME = "vf_vhdl_vs_c.csv"
L3_CSV_NAME = "top_pwm_replay_vs_c.csv"


@dataclass
class CaseMetrics:
    case_id: str
    t_acc_s: float | None
    load_tn: float | None
    l2: dict | None
    l3: dict | None
    l2_csv: Path | None
    l3_csv: Path | None


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def find_latest_campaign() -> Path:
    candidates = sorted(p for p in RESULTS_ROOT.glob("*campaign*") if p.is_dir())
    if not candidates:
        raise SystemExit(f"Nenhuma campanha encontrada em {RESULTS_ROOT}")
    return candidates[-1]


def find_level_dir(case_dir: Path, pattern: str) -> Path | None:
    matches = sorted(p for p in case_dir.glob(pattern) if p.is_dir())
    return matches[0] if matches else None


def load_case_metrics(campaign_dir: Path, case: dict) -> CaseMetrics:
    case_dir = campaign_dir / case["dir"]
    l2_dir = find_level_dir(case_dir, "l2_vf_*_realts")
    l3_dir = find_level_dir(case_dir, "l3_top_pwm_replay_vf_*")
    l2_doc = load_json(l2_dir / "metrics.json") if l2_dir else None
    l3_doc = load_json(l3_dir / "metrics.json") if l3_dir else None
    l2_csv = l2_dir / L2_CSV_NAME if l2_dir and (l2_dir / L2_CSV_NAME).is_file() else None
    l3_csv = l3_dir / L3_CSV_NAME if l3_dir and (l3_dir / L3_CSV_NAME).is_file() else None
    return CaseMetrics(
        case_id=case["id"],
        t_acc_s=case.get("t_acc_s"),
        load_tn=case.get("load_tn"),
        l2=(l2_doc or {}).get("metrics"),
        l3=(l3_doc or {}).get("metrics"),
        l2_csv=l2_csv,
        l3_csv=l3_csv,
    )


def load_grupo_a(campaign_dir: Path) -> list[CaseMetrics]:
    manifest = load_json(campaign_dir / "manifest.json")
    if manifest is None:
        raise SystemExit(f"manifest.json não encontrado em {campaign_dir}")
    by_id = {c["id"]: c for c in manifest["cases"]}
    cases = [by_id[cid] for cid in GRUPO_A_IDS if cid in by_id]
    return [load_case_metrics(campaign_dir, c) for c in cases]


def write_gaps_report(cases: list[CaseMetrics], out_path: Path) -> None:
    missing = [
        f"- {c.case_id}: {level} ausente (metrics.json não encontrado)"
        for c in cases
        for level, val in (("L2", c.l2), ("L3", c.l3))
        if val is None
    ]
    lines = ["# Lacunas de dados — Grupo A", ""]
    lines.append("Nenhuma lacuna encontrada." if not missing else "\n".join(missing))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_csv_columns(path: Path, columns: list[str]) -> dict[str, list[float]]:
    data: dict[str, list[float]] = {c: [] for c in columns}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            for c in columns:
                data[c].append(float(row[c]))
    return data
