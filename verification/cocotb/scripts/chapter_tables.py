#!/usr/bin/env python3
"""Gera as tabelas LaTeX (.tex) do capitulo de resultados (Grupo A e B).

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

# Restrito aos pontos validos sob V/f em malha aberta (A1, A3, A5) -- ver
# docs/superpowers/specs/2026-07-11-simplificacao-matriz-vf-design.md.
T_ACC_ROWS = [0.5, 1.0, 5.0]
LOAD_COLS = [0.0, 0.5]


def fmt_pct(x: float | None) -> str:
    return "--" if x is None else f"{x * 100:.2f}\\%"


def fmt_sci(x: float | None) -> str:
    return "--" if x is None else f"{x:.3g}"


def fmt_ms(x: float | None) -> str:
    return "--" if x is None else f"{x * 1000:.3f}"


def fmt_seconds(x: float, decimals: int) -> str:
    return f"{x:.{decimals}f}"


def fmt_factor(x: float | None) -> str:
    return "--" if x is None else f"{x:.0f}\\times"


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


def render_parametros_grupo_b(cases: list[cc.CaseMetrics], t_n: float | None) -> str:
    lines = [
        "\\begin{tabular}{lccc}",
        "\\toprule",
        "Caso & Carga inicial & Carga final & Sentido \\\\",
        "\\midrule",
    ]
    for c in cases:
        if t_n is None or c.tload_pre_nm is None or c.tload_post_nm is None:
            lines.append(f"{c.case_id} & -- & -- & -- \\\\")
            continue
        pre = c.tload_pre_nm / t_n
        post = c.tload_post_nm / t_n
        sentido = "subida" if post > pre else "descida"
        lines.append(f"{c.case_id} & {pre:.2g}~T_n & {post:.2g}~T_n & {sentido} \\\\")
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


def _render_metricas_table(cases: list[cc.CaseMetrics]) -> str:
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


def render_metricas_grupo_a(cases: list[cc.CaseMetrics]) -> str:
    return _render_metricas_table(cases)


def render_metricas_grupo_b(cases: list[cc.CaseMetrics]) -> str:
    return _render_metricas_table(cases)


def _transient_cells(t: dict | None) -> list[str]:
    if not t:
        return ["--", "--", "--", "--"]
    vhdl = t.get("vhdl", {})
    c = t.get("c", {})
    return [
        fmt_sci(vhdl.get("speed_peak_deviation_rad_s")),
        fmt_sci(c.get("speed_peak_deviation_rad_s")),
        fmt_ms(vhdl.get("recovery_time_s")),
        fmt_ms(c.get("recovery_time_s")),
    ]


def render_transiente_grupo_b(cases: list[cc.CaseMetrics]) -> str:
    lines = [
        "\\begin{tabular}{lcccc}",
        "\\toprule",
        " & \\multicolumn{2}{c}{Desvio pico vel. [rad/s]} & \\multicolumn{2}{c}{Tempo recuperação [ms]} \\\\",
        "Caso (nível) & VHDL & C/C++ & VHDL & C/C++ \\\\",
        "\\midrule",
    ]
    for c in cases:
        if c.l2_transient is not None:
            lines.append(f"{c.case_id} (L2) & " + " & ".join(_transient_cells(c.l2_transient)) + " \\\\")
        if c.l3_transient is not None:
            lines.append(f"{c.case_id} (L3) & " + " & ".join(_transient_cells(c.l3_transient)) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def _timing_row(case_id: str, level: str, timing: tuple[float, float] | None) -> str | None:
    if timing is None:
        return None
    sim_s, wall_s = timing
    factor = wall_s / sim_s if sim_s > 0 else None
    return (f"{case_id} ({level}) & {fmt_seconds(sim_s, 3)} & {fmt_seconds(wall_s, 1)} "
            f"& {fmt_factor(factor)} \\\\")


def render_tempo_simulacao(cases: list[cc.CaseMetrics]) -> str:
    lines = [
        "\\begin{tabular}{lccc}",
        "\\toprule",
        "Caso (nível) & Tempo motor [s] & Tempo de parede [s] & Fator \\\\",
        "\\midrule",
    ]
    for c in cases:
        if c.l2_run_log is not None:
            row = _timing_row(c.case_id, "L2", cc.parse_run_log_timing(c.l2_run_log))
            if row:
                lines.append(row)
        if c.l3_run_log is not None:
            row = _timing_row(c.case_id, "L3", cc.parse_run_log_timing(c.l3_run_log))
            if row:
                lines.append(row)
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, default=None)
    ap.add_argument("-o", "--outdir", type=Path,
                     default=cc.REPO_ROOT / "docs" / "results-chapter" / "tables")
    args = ap.parse_args()

    campaign_dir = (args.campaign or cc.find_latest_campaign()).resolve()
    cases_a = cc.load_grupo_a(campaign_dir)
    cases_b = cc.load_grupo_b(campaign_dir)
    t_n = cc.load_defaults(campaign_dir).get("torque_nominal_nm")

    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "parametros_grupo_a.tex").write_text(
        render_parametros_grupo_a(cases_a), encoding="utf-8")
    (args.outdir / "metricas_grupo_a.tex").write_text(
        render_metricas_grupo_a(cases_a), encoding="utf-8")
    (args.outdir / "parametros_grupo_b.tex").write_text(
        render_parametros_grupo_b(cases_b, t_n), encoding="utf-8")
    (args.outdir / "metricas_grupo_b.tex").write_text(
        render_metricas_grupo_b(cases_b), encoding="utf-8")
    (args.outdir / "transiente_grupo_b.tex").write_text(
        render_transiente_grupo_b(cases_b), encoding="utf-8")
    (args.outdir / "tempo_simulacao.tex").write_text(
        render_tempo_simulacao(cases_a + cases_b), encoding="utf-8")
    cc.write_gaps_report(cases_a + cases_b, args.outdir.parent / "gaps.md")
    print(f"Tabelas geradas em {args.outdir}")


if __name__ == "__main__":
    main()
