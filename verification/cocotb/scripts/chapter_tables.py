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
