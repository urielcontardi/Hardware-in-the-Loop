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

    line_styles = [
        ("-", "o"),
        ("--", "s"),
        (":", "^"),
    ]
    for (label, ids), (linestyle, marker) in zip(TREND_GROUPS.items(), line_styles):
        pts = sorted(
            (by_id[cid].load_tn, by_id[cid].l2["nrmse_i_alpha"] * 100)
            for cid in ids if cid in by_id
        )
        if pts:
            ax_load.plot(*zip(*pts), marker=marker, linestyle=linestyle,
                          color="black", label=label)
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
