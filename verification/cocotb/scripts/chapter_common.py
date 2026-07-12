#!/usr/bin/env python3
"""Shared data loading for the results-chapter table generators.

Reads manifest.json plus per-case metrics.json/CSV/run.log straight from
disk on every call. Never trusts the `status` field or the
`l2_results`/`l3_results` keys in manifest.json -- those have been observed
stale or incomplete on campaign_03 (several Grupo A cases show
`l2_results: {}` even though `metrics.json` exists on disk; all of Grupo B
does too). File existence on disk is the only source of truth: each case's
L2/L3 directory is found by globbing inside the case's own directory, not
by reading manifest pointers.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "verification" / "results"

# Restrito aos casos validos sob V/f em malha aberta (sem boost/compensacao de
# escorregamento): A2/A4/A6/A7 e a carga inicial de B3 divergem para
# velocidade negativa fora de escala fisica sob carga >= 0.75 Tn aplicada
# desde o repouso -- achado documentado em
# docs/superpowers/specs/2026-07-11-simplificacao-matriz-vf-design.md.
GRUPO_A_IDS = ["A1", "A3", "A5"]
GRUPO_B_IDS = ["B1", "B2"]

L2_CSV_NAME = "vf_vhdl_vs_c.csv"
L3_CSV_NAME = "top_pwm_replay_vs_c.csv"

L2_DIR_PATTERNS = {"a": "l2_vf_*_realts", "b": "l2_step_*"}
L3_DIR_PATTERNS = {"a": "l3_top_pwm_replay_vf_*", "b": "l3_top_pwm_replay_step_*"}

TESTS_LINE_RE = re.compile(
    r"TESTS=\d+\s+PASS=\d+\s+FAIL=\d+\s+SKIP=\d+\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
)


@dataclass
class CaseMetrics:
    case_id: str
    t_acc_s: float | None
    load_tn: float | None
    l2: dict | None
    l3: dict | None
    l2_csv: Path | None
    l3_csv: Path | None
    group: str = "a"
    tload_pre_nm: float | None = None
    tload_post_nm: float | None = None
    t_step_s: float | None = None
    l2_transient: dict | None = None
    l3_transient: dict | None = None
    l2_run_log: Path | None = None
    l3_run_log: Path | None = None


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


def load_defaults(campaign_dir: Path) -> dict:
    manifest = load_json(campaign_dir / "manifest.json") or {}
    return manifest.get("defaults", {})


def parse_run_log_timing(run_log_path: Path) -> tuple[float, float] | None:
    """Extract (sim_time_s, wall_time_s) from cocotb's own `TESTS=` summary
    line at the end of a run.log. Returns None if the file is missing or
    the line isn't found (e.g. the fullstack_mock cases, which aren't
    cocotb runs at all)."""
    if not run_log_path.is_file():
        return None
    match = None
    for line in run_log_path.read_text(errors="replace").splitlines():
        found = TESTS_LINE_RE.search(line)
        if found:
            match = found
    if match is None:
        return None
    sim_time_ns, wall_time_s, _ratio = (float(g) for g in match.groups())
    return sim_time_ns / 1e9, wall_time_s


def load_case_metrics(campaign_dir: Path, case: dict, group: str = "a") -> CaseMetrics:
    case_dir = campaign_dir / case["dir"]
    l2_dir = find_level_dir(case_dir, L2_DIR_PATTERNS[group])
    l3_dir = find_level_dir(case_dir, L3_DIR_PATTERNS[group])
    l2_doc = load_json(l2_dir / "metrics.json") if l2_dir else None
    l3_doc = load_json(l3_dir / "metrics.json") if l3_dir else None
    l2_csv = l2_dir / L2_CSV_NAME if l2_dir and (l2_dir / L2_CSV_NAME).is_file() else None
    l3_csv = l3_dir / L3_CSV_NAME if l3_dir and (l3_dir / L3_CSV_NAME).is_file() else None
    l2_run_log = l2_dir / "run.log" if l2_dir and (l2_dir / "run.log").is_file() else None
    l3_run_log = l3_dir / "run.log" if l3_dir and (l3_dir / "run.log").is_file() else None
    return CaseMetrics(
        case_id=case["id"],
        t_acc_s=case.get("t_acc_s"),
        load_tn=case.get("load_tn"),
        l2=(l2_doc or {}).get("metrics"),
        l3=(l3_doc or {}).get("metrics"),
        l2_csv=l2_csv,
        l3_csv=l3_csv,
        group=group,
        tload_pre_nm=case.get("tload_pre_nm"),
        tload_post_nm=case.get("tload_post_nm"),
        t_step_s=case.get("t_step_s"),
        l2_transient=(l2_doc or {}).get("transient"),
        l3_transient=(l3_doc or {}).get("transient"),
        l2_run_log=l2_run_log,
        l3_run_log=l3_run_log,
    )


def _load_group(campaign_dir: Path, ids: list[str], group: str) -> list[CaseMetrics]:
    manifest = load_json(campaign_dir / "manifest.json")
    if manifest is None:
        raise SystemExit(f"manifest.json não encontrado em {campaign_dir}")
    by_id = {c["id"]: c for c in manifest["cases"]}
    cases = [by_id[cid] for cid in ids if cid in by_id]
    return [load_case_metrics(campaign_dir, c, group) for c in cases]


def load_grupo_a(campaign_dir: Path) -> list[CaseMetrics]:
    return _load_group(campaign_dir, GRUPO_A_IDS, "a")


def load_grupo_b(campaign_dir: Path) -> list[CaseMetrics]:
    return _load_group(campaign_dir, GRUPO_B_IDS, "b")


def write_gaps_report(cases: list[CaseMetrics], out_path: Path) -> None:
    missing = [
        f"- {c.case_id}: {level} ausente (metrics.json não encontrado)"
        for c in cases
        for level, val in (("L2", c.l2), ("L3", c.l3))
        if val is None
    ]
    lines = ["# Lacunas de dados", ""]
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
