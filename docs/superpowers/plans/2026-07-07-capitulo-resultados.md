# Capítulo de Resultados — Conteúdo e Ferramenta de Geração — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the scripts that generate LaTeX tables and vector PDF figures for the dissertation's results chapter (Grupo A: S0/A1-A7) directly from `verification/results/*_campaign_*/`, plus a D2 diagram explaining the S0 → Grupo A → Grupo B sequence.

**Architecture:** A shared read-only data-loading module (`chapter_common.py`) resolves what actually exists on disk for each Grupo A case (never trusting the manifest's `status`/`l2_results`/`l3_results`, which are stale/incomplete). Two thin CLI scripts (`chapter_tables.py`, `chapter_figures.py`) consume that module to emit `.tex` tables and `.pdf` figures into a new versioned directory, `docs/results-chapter/`. A new `docs/diagrams/06-validation-groups.d2` follows the existing monochrome diagram convention.

**Tech Stack:** Python 3.12, `matplotlib` (new dependency, Agg backend, PDF output), stdlib `csv`/`json`, `pytest` (existing), D2 (existing).

## Global Constraints

- File existence on disk is the only source of truth for what data is available — never branch on `manifest.json`'s `status` field or on the presence of keys in `l2_results`/`l3_results` (confirmed stale: A2/A3/A4/A6/A7 have `l2_results: {}` in `verification/results/2026-07-04_campaign_03/manifest.json` despite `metrics.json` existing on disk).
- Missing data (case/level not found) must never raise — render as `--` in tables, skip in figures with a `stderr` warning.
- Figures: matplotlib, `Agg` backend, saved as vector PDF (`fig.savefig(path)` with a `.pdf` suffix — matplotlib picks the PDF backend from the extension).
- Tables: plain LaTeX using `booktabs` commands (`\toprule`/`\midrule`/`\bottomrule`), no other package assumed.
- Output directory `docs/results-chapter/{figures,tables}/` is versioned (tracked by git) — unlike `verification/results/`, which stays gitignored.
- Scripts live in `verification/cocotb/scripts/`, tests in `verification/cocotb/scripts/tests/`, following the existing style of `build_campaign_dashboard.py` (`REPO_ROOT = Path(__file__).resolve().parents[3]`, `load_json` returns `None` on missing/malformed file, `find_latest_campaign()` picks the newest `verification/results/*campaign*/` directory).
- D2 diagrams stay monochrome (black/white/gray only): solid border = executed, dashed border = pending — matches the `box`/`pending` classes already used in `docs/diagrams/00-system.d2` (there called `box`/`cdc`).

---

### Task 1: `chapter_common.py` — shared data loader

**Files:**
- Create: `verification/cocotb/scripts/chapter_common.py`
- Test: `verification/cocotb/scripts/tests/test_chapter_common.py`

**Interfaces:**
- Produces (used by Task 2 and Task 3):
  - `REPO_ROOT: Path`, `RESULTS_ROOT: Path`, `GRUPO_A_IDS: list[str]`
  - `@dataclass CaseMetrics(case_id: str, t_acc_s: float | None, load_tn: float | None, l2: dict | None, l3: dict | None, l2_csv: Path | None, l3_csv: Path | None)`
  - `load_json(path: Path) -> dict | None`
  - `find_latest_campaign() -> Path`
  - `load_grupo_a(campaign_dir: Path) -> list[CaseMetrics]`
  - `write_gaps_report(cases: list[CaseMetrics], out_path: Path) -> None`
  - `load_csv_columns(path: Path, columns: list[str]) -> dict[str, list[float]]`

- [ ] **Step 1: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_chapter_common.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc


def _write_metrics(path: Path, nrmse_a: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "metrics": {
            "nrmse_i_alpha": nrmse_a,
            "nrmse_i_beta": nrmse_a * 0.9,
            "mae_flux_alpha_wb": 0.001,
            "mae_flux_beta_wb": 0.0011,
            "mae_speed_rad_s": 0.3,
        }
    }))


def _manifest() -> dict:
    return {
        "cases": [
            {"id": "A1", "dir": "A1_tacc0p5s_load000", "t_acc_s": 0.5, "load_tn": 0.0,
             "l2_results": {}, "l3_results": {}},
            {"id": "A2", "dir": "A2_tacc0p5s_load100", "t_acc_s": 0.5, "load_tn": 1.0,
             "l2_results": {}, "l3_results": {}},
        ]
    }


def test_load_grupo_a_finds_metrics_ignoring_manifest_results_dict(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A2_tacc0p5s_load100/l2_vf_500ms_realts/metrics.json", 0.02)
    # A2 has no l3 dir at all -- simulates L2 done, L3 still pending

    cases = cc.load_grupo_a(tmp_path)

    assert [c.case_id for c in cases] == ["A1", "A2"]
    a1, a2 = cases
    assert a1.l2["nrmse_i_alpha"] == 0.03
    assert a1.l3["nrmse_i_alpha"] == 0.031
    assert a2.l2["nrmse_i_alpha"] == 0.02
    assert a2.l3 is None


def test_write_gaps_report_lists_missing_levels(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A2_tacc0p5s_load100/l2_vf_500ms_realts/metrics.json", 0.02)

    cases = cc.load_grupo_a(tmp_path)
    out_path = tmp_path / "gaps.md"
    cc.write_gaps_report(cases, out_path)

    text = out_path.read_text()
    assert "A2: L3 ausente (metrics.json não encontrado)" in text
    assert "A1: L2 ausente" not in text
    assert "A1: L3 ausente" not in text


def test_load_csv_columns_parses_floats(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("t_us,vhdl_i_alpha\n0,0.1\n10,0.2\n")

    data = cc.load_csv_columns(csv_path, ["t_us", "vhdl_i_alpha"])

    assert data["t_us"] == [0.0, 10.0]
    assert data["vhdl_i_alpha"] == [0.1, 0.2]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_common.py -v
```

Expected: `ModuleNotFoundError: No module named 'chapter_common'` (module doesn't exist yet).

- [ ] **Step 3: Implement `chapter_common.py`**

Create `verification/cocotb/scripts/chapter_common.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_common.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/chapter_common.py verification/cocotb/scripts/tests/test_chapter_common.py
git commit -m "$(cat <<'EOF'
feat(validation): chapter_common — loader robusto p/ capitulo de resultados

Resolve L2/L3 por glob no diretorio do caso, nao pelas chaves do
manifest (l2_results/l3_results ficaram vazias para A2/A3/A4/A6/A7
mesmo com metrics.json em disco).
EOF
)"
```

---

### Task 2: `chapter_tables.py` — LaTeX tables

**Files:**
- Create: `verification/cocotb/scripts/chapter_tables.py`
- Test: `verification/cocotb/scripts/tests/test_chapter_tables.py`

**Interfaces:**
- Consumes: `chapter_common.CaseMetrics`, `chapter_common.load_grupo_a`, `chapter_common.find_latest_campaign`, `chapter_common.write_gaps_report`, `chapter_common.REPO_ROOT` (Task 1).
- Produces: `render_parametros_grupo_a(cases: list[CaseMetrics]) -> str`, `render_metricas_grupo_a(cases: list[CaseMetrics]) -> str` (used only by this script's `main()`, no other task consumes these directly).

- [ ] **Step 1: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_chapter_tables.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc
import chapter_tables as ct


def _case(case_id, t_acc, load, l2=None, l3=None):
    return cc.CaseMetrics(case_id=case_id, t_acc_s=t_acc, load_tn=load,
                           l2=l2, l3=l3, l2_csv=None, l3_csv=None)


def test_render_parametros_grupo_a_places_cases_in_matrix():
    cases = [_case("A1", 0.5, 0.0), _case("A2", 0.5, 1.0)]

    tex = ct.render_parametros_grupo_a(cases)

    row_05 = next(line for line in tex.splitlines() if line.startswith("0.5~s"))
    cells = [c.strip() for c in row_05.split("&")]
    assert cells[1] == "A1"   # carga = 0.0
    assert cells[3] == "A2"   # carga = 1.0


def test_render_metricas_grupo_a_uses_dashes_for_missing_level():
    metrics = {
        "nrmse_i_alpha": 0.03, "nrmse_i_beta": 0.03,
        "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.001,
        "mae_speed_rad_s": 0.3,
    }
    cases = [_case("A1", 0.5, 0.0, l2=metrics, l3=None)]

    tex = ct.render_metricas_grupo_a(cases)

    row = next(line for line in tex.splitlines() if line.startswith("A1"))
    cells = [c.strip() for c in row.rstrip("\\").split("&")]
    assert cells[1] == "3.00\\%"  # L2 nrmse_i_alpha
    assert cells[-1] == "--"      # L3 mae_speed_rad_s, missing
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_tables.py -v
```

Expected: `ModuleNotFoundError: No module named 'chapter_tables'`.

- [ ] **Step 3: Implement `chapter_tables.py`**

Create `verification/cocotb/scripts/chapter_tables.py`:

```python
#!/usr/bin/env python3
"""Gera as tabelas LaTeX (.tex) do capitulo de resultados (Grupo A).

Usage:
    python3 chapter_tables.py [--campaign DIR] [-o OUTDIR]

Default campaign: mais recente em verification/results/*_campaign_*/.
Default outdir: docs/results-chapter/tables/ (raiz do repo).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_common as cc

T_ACC_ROWS = [0.5, 1.0, 2.0, 5.0]
LOAD_COLS = [0.0, 0.5, 1.0, 1.1]


def fmt_pct(x: float | None) -> str:
    return "--" if x is None else f"{x * 100:.2f}\\%"


def fmt_sci(x: float | None) -> str:
    return "--" if x is None else f"{x:.3g}"


def render_parametros_grupo_a(cases: list[cc.CaseMetrics]) -> str:
    coord = {
        (round(c.t_acc_s, 3), round(c.load_tn, 3)): c.case_id
        for c in cases if c.t_acc_s is not None and c.load_tn is not None
    }
    lines = [
        "\\begin{tabular}{l" + "c" * len(LOAD_COLS) + "}",
        "\\toprule",
        "$t_{acc}$ / carga & " + " & ".join(f"{v:g}~T_n" for v in LOAD_COLS) + " \\\\",
        "\\midrule",
    ]
    for t in T_ACC_ROWS:
        row_cells = [coord.get((round(t, 3), round(l, 3)), "") for l in LOAD_COLS]
        lines.append(f"{t:g}~s & " + " & ".join(row_cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def _metric_cells(m: dict) -> list[str]:
    return [
        fmt_pct(m.get("nrmse_i_alpha")),
        fmt_pct(m.get("nrmse_i_beta")),
        fmt_sci(m.get("mae_flux_alpha_wb")),
        fmt_sci(m.get("mae_flux_beta_wb")),
        fmt_sci(m.get("mae_speed_rad_s")),
    ]


def render_metricas_grupo_a(cases: list[cc.CaseMetrics]) -> str:
    per_level = ["$i_\\alpha$", "$i_\\beta$", "$\\phi_\\alpha$", "$\\phi_\\beta$", "$\\omega$"]
    lines = [
        "\\begin{tabular}{l" + "c" * 10 + "}",
        "\\toprule",
        " & \\multicolumn{5}{c}{L2} & \\multicolumn{5}{c}{L3} \\\\",
        "Caso & " + " & ".join(per_level) + " & " + " & ".join(per_level) + " \\\\",
        "\\midrule",
    ]
    for c in cases:
        cells = _metric_cells(c.l2 or {}) + _metric_cells(c.l3 or {})
        lines.append(f"{c.case_id} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, default=None)
    ap.add_argument("-o", "--outdir", type=Path,
                     default=cc.REPO_ROOT / "docs" / "results-chapter" / "tables")
    args = ap.parse_args()

    campaign_dir = (args.campaign or cc.find_latest_campaign()).resolve()
    cases = cc.load_grupo_a(campaign_dir)

    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "parametros_grupo_a.tex").write_text(
        render_parametros_grupo_a(cases), encoding="utf-8")
    (args.outdir / "metricas_grupo_a.tex").write_text(
        render_metricas_grupo_a(cases), encoding="utf-8")
    cc.write_gaps_report(cases, args.outdir.parent / "gaps.md")
    print(f"Tabelas geradas em {args.outdir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_tables.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run against the real campaign_03 and eyeball the output**

```bash
cd verification/cocotb
uv run python3 scripts/chapter_tables.py
cat ../../docs/results-chapter/tables/parametros_grupo_a.tex
cat ../../docs/results-chapter/tables/metricas_grupo_a.tex
cat ../../docs/results-chapter/gaps.md
```

Expected: `parametros_grupo_a.tex` shows A1-A7 placed at their `(t_acc, carga)` cell; `metricas_grupo_a.tex` has one row per case with real NRMSE/MAE numbers (not all `--`, since A1-A7 currently have both L2 and L3 data on disk); `gaps.md` says "Nenhuma lacuna encontrada." (current state) or lists any case that has gone missing since this plan was written.

- [ ] **Step 6: Commit**

```bash
git add verification/cocotb/scripts/chapter_tables.py verification/cocotb/scripts/tests/test_chapter_tables.py docs/results-chapter/
git commit -m "$(cat <<'EOF'
feat(validation): chapter_tables — tabelas LaTeX do Grupo A

Gera parametros_grupo_a.tex (matriz t_acc x carga) e
metricas_grupo_a.tex (NRMSE/MAE L2 vs L3 por caso) a partir da
campanha mais recente, tolerante a caso/nivel ausente.
EOF
)"
```

---

### Task 3: `chapter_figures.py` — matplotlib PDF figures

**Files:**
- Modify: `verification/cocotb/pyproject.toml` (add `matplotlib` dependency)
- Create: `verification/cocotb/scripts/chapter_figures.py`
- Test: `verification/cocotb/scripts/tests/test_chapter_figures.py`

**Interfaces:**
- Consumes: `chapter_common.CaseMetrics`, `chapter_common.load_grupo_a`, `chapter_common.load_csv_columns`, `chapter_common.find_latest_campaign`, `chapter_common.REPO_ROOT` (Task 1).
- Produces: `plot_forma_onda(case: CaseMetrics, out_path: Path) -> bool`, `plot_resumo_l2_vs_l3(cases: list[CaseMetrics], out_path: Path) -> None`, `plot_resumo_tendencia(cases: list[CaseMetrics], out_path: Path) -> None` — used only by this script's `main()`.

- [ ] **Step 1: Add the matplotlib dependency**

```bash
cd verification/cocotb
uv add matplotlib
uv run python3 -c "import matplotlib; print(matplotlib.__version__)"
```

Expected: prints a version string (e.g. `3.9.x`), and `verification/cocotb/pyproject.toml` now lists `matplotlib` under `dependencies`.

- [ ] **Step 2: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_chapter_figures.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc
import chapter_figures as cf


def _write_metrics(path: Path, nrmse_a: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metrics": {
        "nrmse_i_alpha": nrmse_a, "nrmse_i_beta": nrmse_a * 0.9,
        "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.0011,
        "mae_speed_rad_s": 0.3,
    }}))


def _write_csv(path: Path, time_col: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [time_col, "vhdl_i_alpha", "ref_i_alpha", "vhdl_i_beta", "ref_i_beta",
              "vhdl_speed", "ref_speed"]
    rows = [
        [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [1, 0.5, 0.4, 0.3, 0.25, 1.0, 0.9],
        [2, 1.0, 0.9, 0.6, 0.55, 2.0, 1.9],
    ]
    lines = [",".join(header)] + [",".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")


def _build_campaign(tmp_path: Path) -> Path:
    manifest = {"cases": [
        {"id": "A1", "dir": "A1_tacc0p5s_load000", "t_acc_s": 0.5, "load_tn": 0.0},
        {"id": "A5", "dir": "A5_tacc5s_load000", "t_acc_s": 5.0, "load_tn": 0.0},
    ]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_csv(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/top_pwm_replay_vs_c.csv", "t_s")
    _write_metrics(tmp_path / "A5_tacc5s_load000/l2_vf_5s_realts/metrics.json", 0.04)
    return tmp_path


def test_plot_forma_onda_writes_nonempty_pdf(tmp_path):
    campaign_dir = _build_campaign(tmp_path)
    cases = cc.load_grupo_a(campaign_dir)
    a1 = next(c for c in cases if c.case_id == "A1")
    out_path = tmp_path / "out" / "forma_onda_A1.pdf"

    ok = cf.plot_forma_onda(a1, out_path)

    assert ok is True
    assert out_path.stat().st_size > 0


def test_plot_forma_onda_returns_false_without_csv():
    case = cc.CaseMetrics(case_id="X", t_acc_s=1.0, load_tn=0.0,
                           l2=None, l3=None, l2_csv=None, l3_csv=None)

    ok = cf.plot_forma_onda(case, Path("/tmp/should-not-be-created.pdf"))

    assert ok is False


def test_plot_resumo_charts_run_with_partial_data(tmp_path):
    campaign_dir = _build_campaign(tmp_path)
    cases = cc.load_grupo_a(campaign_dir)  # A1 has L2+L3, A5 has only L2
    out1 = tmp_path / "resumo_l2_vs_l3.pdf"
    out2 = tmp_path / "resumo_tendencia.pdf"

    cf.plot_resumo_l2_vs_l3(cases, out1)
    cf.plot_resumo_tendencia(cases, out2)

    assert out1.stat().st_size > 0
    assert out2.stat().st_size > 0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_figures.py -v
```

Expected: `ModuleNotFoundError: No module named 'chapter_figures'`.

- [ ] **Step 4: Implement `chapter_figures.py`**

Create `verification/cocotb/scripts/chapter_figures.py`:

```python
#!/usr/bin/env python3
"""Gera as figuras PDF (matplotlib, vetorial) do capitulo de resultados (Grupo A).

Usage:
    python3 chapter_figures.py [--campaign DIR] [-o OUTDIR] [--case ID ...]

Default campaign: mais recente em verification/results/*_campaign_*/.
Default outdir: docs/results-chapter/figures/ (raiz do repo).
Default --case: A1 A7.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_common as cc

plt.rcParams.update({
    "font.family": "serif",
    "axes.grid": True,
    "grid.color": "#d9d9d9",
    "grid.linewidth": 0.5,
    "axes.edgecolor": "black",
})

TREND_GROUPS = {
    "0,5 s": ["A1", "A2"],
    "2,0 s": ["A4", "A7"],
    "5,0 s": ["A5", "A6"],
}


def plot_forma_onda(case: cc.CaseMetrics, out_path: Path) -> bool:
    if case.l3_csv is not None:
        csv_path, time_col, time_scale = case.l3_csv, "t_s", 1.0
    elif case.l2_csv is not None:
        csv_path, time_col, time_scale = case.l2_csv, "t_us", 1e-6
    else:
        print(f"[aviso] {case.case_id}: sem CSV (L2 nem L3), figura pulada", file=sys.stderr)
        return False

    cols = [time_col, "vhdl_i_alpha", "ref_i_alpha", "vhdl_i_beta", "ref_i_beta",
            "vhdl_speed", "ref_speed"]
    data = cc.load_csv_columns(csv_path, cols)
    t = [x * time_scale for x in data[time_col]]

    fig, axes = plt.subplots(3, 1, figsize=(6, 6), sharex=True)
    pairs = [
        ("vhdl_i_alpha", "ref_i_alpha", "$i_\\alpha$ [A]"),
        ("vhdl_i_beta", "ref_i_beta", "$i_\\beta$ [A]"),
        ("vhdl_speed", "ref_speed", "$\\omega$ [rad/s]"),
    ]
    for ax, (vhdl_k, ref_k, ylabel) in zip(axes, pairs):
        ax.plot(t, data[ref_k], color="0.5", linestyle="--", label="Referência C/C++")
        ax.plot(t, data[vhdl_k], color="black", linestyle="-", label="VHDL")
        ax.set_ylabel(ylabel)
    axes[0].legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("Tempo [s]")
    fig.suptitle(f"Caso {case.case_id}")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return True


def plot_resumo_l2_vs_l3(cases: list[cc.CaseMetrics], out_path: Path) -> None:
    rows = [c for c in cases if c.l2 is not None and c.l3 is not None]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))
    for ax, key, title in zip(axes, ("nrmse_i_alpha", "nrmse_i_beta"),
                               ("$i_\\alpha$ NRMSE", "$i_\\beta$ NRMSE")):
        x = list(range(len(rows)))
        width = 0.35
        ax.bar([i - width / 2 for i in x], [r.l2[key] * 100 for r in rows], width,
               color="0.7", label="L2")
        ax.bar([i + width / 2 for i in x], [r.l3[key] * 100 for r in rows], width,
               color="black", label="L3")
        ax.set_xticks(x)
        ax.set_xticklabels([r.case_id for r in rows])
        ax.set_ylabel("NRMSE [%]")
        ax.set_title(title)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def plot_resumo_tendencia(cases: list[cc.CaseMetrics], out_path: Path) -> None:
    by_id = {c.case_id: c for c in cases if c.l2 is not None}
    fig, (ax_tacc, ax_load) = plt.subplots(1, 2, figsize=(8, 3.5))

    pts = sorted(
        (by_id[cid].t_acc_s, by_id[cid].l2["nrmse_i_alpha"] * 100)
        for cid in ("A1", "A5") if cid in by_id
    )
    if pts:
        ax_tacc.plot(*zip(*pts), marker="o", color="black")
    ax_tacc.set_xlabel("$t_{acc}$ [s] (carga = 0)")
    ax_tacc.set_ylabel("$i_\\alpha$ NRMSE [%]")

    for label, ids in TREND_GROUPS.items():
        pts = sorted(
            (by_id[cid].load_tn, by_id[cid].l2["nrmse_i_alpha"] * 100)
            for cid in ids if cid in by_id
        )
        if pts:
            ax_load.plot(*zip(*pts), marker="o", label=label)
    if "A3" in by_id:
        ax_load.plot(by_id["A3"].load_tn, by_id["A3"].l2["nrmse_i_alpha"] * 100,
                      marker="x", color="black", linestyle="none", label="A3 (sem par)")
    ax_load.set_xlabel("Carga [$T_n$]")
    ax_load.set_ylabel("$i_\\alpha$ NRMSE [%]")
    ax_load.legend(fontsize=7)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, default=None)
    ap.add_argument("-o", "--outdir", type=Path,
                     default=cc.REPO_ROOT / "docs" / "results-chapter" / "figures")
    ap.add_argument("--case", action="append", default=None,
                     help="Caso(s) para forma de onda (default: A1 A7)")
    args = ap.parse_args()

    campaign_dir = (args.campaign or cc.find_latest_campaign()).resolve()
    cases = cc.load_grupo_a(campaign_dir)
    by_id = {c.case_id: c for c in cases}

    for case_id in (args.case or ["A1", "A7"]):
        case = by_id.get(case_id)
        if case is None:
            print(f"[aviso] caso {case_id} não encontrado na campanha, pulando", file=sys.stderr)
            continue
        plot_forma_onda(case, args.outdir / f"forma_onda_{case_id}.pdf")

    plot_resumo_l2_vs_l3(cases, args.outdir / "resumo_l2_vs_l3.pdf")
    plot_resumo_tendencia(cases, args.outdir / "resumo_tendencia.pdf")
    print(f"Figuras geradas em {args.outdir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_chapter_figures.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run against the real campaign_03 and confirm the PDFs open**

```bash
cd verification/cocotb
uv run python3 scripts/chapter_figures.py
ls -la ../../docs/results-chapter/figures/
```

Expected: `forma_onda_A1.pdf`, `forma_onda_A7.pdf`, `resumo_l2_vs_l3.pdf`, `resumo_tendencia.pdf`, all non-empty. Open at least one to confirm it renders (not just non-zero size).

- [ ] **Step 7: Commit**

```bash
git add verification/cocotb/pyproject.toml verification/cocotb/uv.lock \
        verification/cocotb/scripts/chapter_figures.py \
        verification/cocotb/scripts/tests/test_chapter_figures.py \
        docs/results-chapter/figures/
git commit -m "$(cat <<'EOF'
feat(validation): chapter_figures — figuras PDF do Grupo A

Forma de onda (i_alpha/i_beta/velocidade) para casos representativos,
mais dois graficos-resumo (L2 vs L3 por caso; tendencia vs t_acc/carga).
Usa matplotlib (nova dependencia), saida vetorial PDF.
EOF
)"
```

---

### Task 4: D2 diagram — S0 → Grupo A → Grupo B sequence

**Files:**
- Create: `docs/diagrams/06-validation-groups.d2`
- Modify: `docs/diagrams/README.md` (add row to the figure table)

**Interfaces:** none (standalone diagram asset, no code interface).

- [ ] **Step 1: Write the D2 source**

Create `docs/diagrams/06-validation-groups.d2`:

```d2
# =============================================================================
# Figura 06 - Sequencia dos grupos de ensaio da campanha (S0 -> Grupo A -> Grupo B).
# Nao detalha parametros internos (ver tabela da matriz de parametros no capitulo).
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:     {style: {fill: white; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  pending: {style: {fill: white; stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  arrow:   {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

s0: "S0 - Sanity\nvalida o pipeline L2/L3" {class: box}
grupo_a: "Grupo A - Partida e Aceleracao\n7 casos (A1-A7)\nexecutado" {class: box}
grupo_b: "Grupo B - Degrau de Carga\ncodigo pronto\nnao executado" {class: pending}

s0 -> grupo_a: "pipeline validado" {class: arrow}
grupo_a -> grupo_b: "planejado" {class: arrow}
```

- [ ] **Step 2: Render it**

```bash
cd docs/diagrams
./build.sh
```

Expected: `>> 06-validation-groups.d2` printed, then `OK -> docs/diagrams/img/`. If `d2` is not installed, install it first: `curl -fsSL https://d2lang.com/install.sh | sh -s --` (per `docs/diagrams/README.md`).

- [ ] **Step 3: Verify the output**

```bash
ls -la img/06-validation-groups.svg img/06-validation-groups.png
```

Expected: both files exist and are non-empty. Open `img/06-validation-groups.svg` to confirm it shows three boxes left-to-right, `Grupo B` with a dashed border and the other two solid.

- [ ] **Step 4: Add the new figure to the README table**

In `docs/diagrams/README.md`, in the "Figuras (leitura em ordem)" table, add a row after the `05-frontend.d2` row:

```markdown
| `06-validation-groups.d2` | Sequência de validação experimental | S0 → Grupo A → Grupo B, com status de execução |
```

- [ ] **Step 5: Commit**

```bash
git add docs/diagrams/06-validation-groups.d2 docs/diagrams/img/06-validation-groups.svg \
        docs/diagrams/img/06-validation-groups.png docs/diagrams/README.md
git commit -m "$(cat <<'EOF'
docs(diagrams): adiciona figura 06 (sequencia S0 -> Grupo A -> Grupo B)

Segue a convencao monocromatica existente: borda solida = executado,
borda tracejada = pendente (Grupo B, codigo pronto mas nao rodado).
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Requisito do spec | Task |
|---|---|
| Regra de ouro (arquivo em disco, não manifest) | Task 1 (`find_level_dir` via glob) |
| Tabela matriz de parâmetros (t_acc × carga) | Task 2 (`render_parametros_grupo_a`) |
| Tabela de métricas L2/L3 por caso | Task 2 (`render_metricas_grupo_a`) |
| Nota de rodapé NRMSE L2/L3 vs L4 | Não é código — fica para quando o texto do capítulo for escrito (fora de escopo deste plano, já anotado no spec como tal) |
| Figuras de forma de onda A1/A7 | Task 3 (`plot_forma_onda`) |
| Gráfico-resumo L2 vs L3 | Task 3 (`plot_resumo_l2_vs_l3`) |
| Gráfico-resumo tendência vs t_acc/carga | Task 3 (`plot_resumo_tendencia`) |
| `gaps.md`/relatório de lacunas | Task 1 (`write_gaps_report`), chamado em Task 2's `main()` |
| Diagrama D2 da sequência de grupos | Task 4 |
| Diretório versionado `docs/results-chapter/` | Task 2/3 (`--outdir` defaults) |
| Achados metodológicos, texto do capítulo, redação final | Fora de escopo (spec explícito) — nenhuma task cobre, corretamente |

**Placeholder scan:** nenhum `TBD`/`TODO`; todo passo tem código completo.

**Type/name consistency:** `CaseMetrics` definido em Task 1 com campos `case_id, t_acc_s, load_tn, l2, l3, l2_csv, l3_csv` — usado com os mesmos nomes em Task 2 (`c.l2`, `c.l3`, `c.case_id`, `c.t_acc_s`, `c.load_tn`) e Task 3 (adicionalmente `c.l2_csv`, `c.l3_csv`). `load_grupo_a`, `load_csv_columns`, `write_gaps_report`, `find_latest_campaign`, `REPO_ROOT` usados com a assinatura exata definida em Task 1 em ambas as tasks seguintes.
