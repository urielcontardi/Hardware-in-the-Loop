#!/usr/bin/env python3
"""Gera figuras L4-B: FPGA real vs. reprodução independente completa em PSIM
(motor de indução nativo do PSIM, nao o modelo C/DLL embutido no mesmo
schematic). Ve docs/superpowers/specs/2026-08-01-l4b-psim-validacao-independente-design.md.

Le os .npz ja mesclados (fpga_*/psim_*, ver psim_csv_to_npz.py) para as
figuras de janela (partida/regime), e le o .hilbin bruto + o CSV bruto do
PSIM para a figura de visao geral (janela completa).

psim_ia/psim_ib sao um par alpha/beta (ver psim_csv_to_npz.py), nao fase
crua -- toda figura trifasica aplica chapter_common.inverse_clarke() neles,
igual ja e feito para fpga_ia/fpga_ib.

Sem painel de fluxo: o motor nativo do PSIM nao expoe fluxo do rotor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l2_figures as eng                # noqa: E402
import chapter_common as cc              # noqa: E402
import hilbin_vs_c as H                  # noqa: E402
import psim_csv_to_npz as psim_mod       # noqa: E402


def _overlap_mask_and_grid(fpga_t: np.ndarray, psim_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Clip fpga_t to the range where psim_t also has data.

    Returns (mask, t_common): mask selects into any array sampled on the
    fpga_t grid, t_common = fpga_t[mask].
    """
    t_lo = max(float(fpga_t.min()), float(psim_t.min()))
    t_hi = min(float(fpga_t.max()), float(psim_t.max()))
    mask = (fpga_t >= t_lo) & (fpga_t <= t_hi)
    return mask, fpga_t[mask]


def load_l4b_segment(case: dict, seg: str, campaign: Path) -> tuple[np.ndarray, dict]:
    """Load one partida/regime .npz, align PSIM onto the FPGA/C time grid.

    Returns (t_ms, data): data has vhdl_i_alpha/vhdl_i_beta/vhdl_speed
    (FPGA, clipped to PSIM's coverage) and ref_i_alpha/ref_i_beta/ref_speed
    (PSIM, interpolated onto the clipped FPGA grid).
    """
    npz_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / f"{seg}.npz"
    d = np.load(npz_path)
    fpga_t = np.asarray(d["fpga_t"], dtype=float)
    psim_t = np.asarray(d["psim_t"], dtype=float)
    mask, t_common = _overlap_mask_and_grid(fpga_t, psim_t)
    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"])[mask],
        "vhdl_i_beta": np.asarray(d["fpga_ib"])[mask],
        "vhdl_speed": np.asarray(d["fpga_speed"])[mask],
        "ref_i_alpha": np.interp(t_common, psim_t, np.asarray(d["psim_ia"])),
        "ref_i_beta": np.interp(t_common, psim_t, np.asarray(d["psim_ib"])),
        "ref_speed": np.interp(t_common, psim_t, np.asarray(d["psim_speed"])),
    }
    t_ms = t_common * 1000.0
    return t_ms, data


def _nrmse_pct(dut: np.ndarray, ref: np.ndarray) -> float:
    """RMSE(dut-ref) normalized by the peak-to-peak range of ref, as a percentage."""
    rmse = float(np.sqrt(np.mean((dut - ref) ** 2)))
    span = float(np.ptp(ref))
    return 100.0 * rmse / span if span > 0 else float("nan")


def _mae(dut: np.ndarray, ref: np.ndarray) -> float:
    return float(np.mean(np.abs(dut - ref)))


def compute_metrics_l4b(data: dict) -> dict[str, float]:
    """NRMSE (%) for i_alpha/i_beta, MAE for speed. No flux metric: the PSIM
    native motor block doesn't expose rotor flux."""
    return {
        "nrmse_i_alpha_pct": _nrmse_pct(data["vhdl_i_alpha"], data["ref_i_alpha"]),
        "nrmse_i_beta_pct": _nrmse_pct(data["vhdl_i_beta"], data["ref_i_beta"]),
        "mae_speed_rad_s": _mae(data["vhdl_speed"], data["ref_speed"]),
    }


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}\\%"


def _fmt_sci(x: float) -> str:
    return f"{x:.3g}"


def render_l4b_table(all_metrics: dict[str, dict[str, dict[str, float]]]) -> str:
    """Table-body fragment only (no \\begin{table}/\\caption/\\label wrapper --
    those are hand-written in 4-Resultados.tex, matching tab:l4-metricas'
    style; see chapter_tables.py::_render_metricas_table for the sibling
    pattern this mirrors)."""
    lines = [
        "\\begin{tabular}{l" + "c" * 6 + "}",
        "\\toprule",
        " & \\multicolumn{3}{c}{Partida} & \\multicolumn{3}{c}{Regime} \\\\",
        "Caso & $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] "
        "& $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] \\\\",
        "\\midrule",
    ]
    for case_id, windows in all_metrics.items():
        p = windows.get("partida", {})
        r = windows.get("regime", {})
        cells = [
            _fmt_pct(p.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(p.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(p.get("mae_speed_rad_s", float("nan"))),
            _fmt_pct(r.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(r.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(r.get("mae_speed_rad_s", float("nan"))),
        ]
        lines.append(f"{case_id} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)


def _seg_case(case: dict, seg: str) -> dict:
    """Per-segment copy of a case dict: fig_id becomes '<Id>_<Partida|Regime>'
    so eng._fig_name produces <fig_prefix>_<Id>_<Partida|Regime>_<Kind> file
    names, matching the existing HIL_L4_<Caso>_<Partida|Regime>_Overlay.pdf
    convention."""
    seg_case = dict(case)
    seg_case["fig_id"] = f"{case['id']}_{seg.capitalize()}"
    return seg_case


def plot_overlay_l4b(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Correntes de fase (a/b/c, via Clarke inversa) + velocidade, FPGA
    (vhdl) vs. PSIM (ref) sobrepostos. Sem painel de fluxo -- PSIM nativo nao
    expoe fluxo do rotor."""
    dut_ia, dut_ib, dut_ic = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_ia, ref_ib, ref_ic = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])
    t_s = t_ms / 1000.0

    fig, axes = plt.subplots(2, 1, figsize=(7, 6), sharex=True)

    dut_label, ref_label = eng._labels(case)
    handles = [
        plt.Line2D([], [], color="black", **eng.VHDL_STYLE, label=dut_label),
        plt.Line2D([], [], color="black", **eng.REF_STYLE, label=ref_label),
    ]

    ax = axes[0]
    for dut_y, ref_y, color in zip((dut_ia, dut_ib, dut_ic), (ref_ia, ref_ib, ref_ic), eng.PHASE_COLORS):
        ax.plot(t_s, dut_y, color=color, **eng.VHDL_STYLE)
        ax.plot(t_s, ref_y, color=color, **eng.REF_STYLE)
    ax.set_ylabel("Corrente [A]")
    ax.set_title("Correntes de fase")
    ax.legend(handles=handles, loc="best", fontsize=8, framealpha=0.9)

    ax = axes[1]
    ax.plot(t_s, data["vhdl_speed"], color=eng.COL_VHDL, **eng.VHDL_STYLE)
    ax.plot(t_s, data["ref_speed"], color=eng.COL_C, **eng.REF_STYLE)
    ax.set_ylabel(r"$\omega_{mec}$ [rad/s]")
    ax.set_xlabel("Tempo [s]")

    fig.tight_layout()
    eng.save_fig(fig, out_dir, eng._fig_name(case, "Overlay"))


def _decimate(n: int, max_pts: int = 6000) -> slice:
    step = max(1, n // max_pts)
    return slice(None, None, step)


def load_full_fpga_l4b(case: dict, campaign: Path) -> dict:
    """Full FPGA capture (all samples), decimated, phase currents via Clarke
    inversa. Mirrors results_explorer_app.py::_load_full_capture."""
    hilbin_path = campaign / case["dir"] / "raw" / "capture.hilbin"
    _, fpga, _ = H.parse_hilbin(hilbin_path)
    fpga = H._clip_fpga(fpga)
    n = fpga["t"].size
    sl = _decimate(n)
    ia, ib, ic = cc.inverse_clarke(fpga["ia"][sl], fpga["ib"][sl])
    return {
        "t": np.asarray(fpga["t"][sl], dtype=float),
        "ia": np.asarray(ia, dtype=float),
        "ib": np.asarray(ib, dtype=float),
        "ic": np.asarray(ic, dtype=float),
        "speed": np.asarray(fpga["speed"][sl], dtype=float),
    }


def load_full_psim_l4b(case: dict, repo_root: Path) -> dict:
    """Full PSIM CSV export (all samples), decimated, phase currents via
    Clarke inversa. Reuses psim_csv_to_npz.to_psim_channels with the full
    [min,max] time range (i.e. no windowing)."""
    df = psim_mod.load_psim_csv(repo_root / case["psim_csv"])
    channels, _branch = psim_mod.to_psim_channels(df, float(df["Time"].min()), float(df["Time"].max()))
    n = channels["psim_t"].size
    sl = _decimate(n)
    ia, ib, ic = cc.inverse_clarke(channels["psim_ia"][sl], channels["psim_ib"][sl])
    return {
        "t": np.asarray(channels["psim_t"][sl], dtype=float),
        "ia": np.asarray(ia, dtype=float),
        "ib": np.asarray(ib, dtype=float),
        "ic": np.asarray(ic, dtype=float),
        "speed": np.asarray(channels["psim_speed"][sl], dtype=float),
    }


def plot_full_overview_l4b(case: dict, out_dir: Path, campaign: Path, repo_root: Path) -> None:
    """Janela completa: correntes de fase + velocidade, FPGA vs. PSIM, com
    as janelas de partida/regime sombreadas (lidas de metrics.json)."""
    fpga = load_full_fpga_l4b(case, campaign)
    psim = load_full_psim_l4b(case, repo_root)

    # Trunca as duas series no menor alcance comum -- sem isso, a serie mais
    # longa (normalmente a FPGA) desenha uma "cauda" sem nada pra comparar,
    # o que so ocupa espaco e pode confundir o leitor.
    t_shared_max = min(float(fpga["t"].max()), float(psim["t"].max()))
    fpga_keep = fpga["t"] <= t_shared_max
    psim_keep = psim["t"] <= t_shared_max
    fpga = {k: v[fpga_keep] for k, v in fpga.items()}
    psim = {k: v[psim_keep] for k, v in psim.items()}

    mj_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / "metrics.json"
    wins: list[tuple[float, float, str, str]] = []
    if mj_path.is_file():
        mj = json.loads(mj_path.read_text())
        for lbl, col in (("partida", eng.PHASE_COLORS[0]), ("regime", eng.PHASE_COLORS[2])):
            w = mj.get(lbl, {}).get("window_s")
            if w:
                wins.append((w[0], w[1], lbl.capitalize(), col))

    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    handles = [
        plt.Line2D([], [], color="black", **eng.VHDL_STYLE, label="FPGA (real)"),
        plt.Line2D([], [], color="black", **eng.REF_STYLE, label="PSIM (independente)"),
    ]

    ax = axes[0]
    for dut_y, ref_y, color in zip((fpga["ia"], fpga["ib"], fpga["ic"]),
                                     (psim["ia"], psim["ib"], psim["ic"]),
                                     eng.PHASE_COLORS):
        ax.plot(fpga["t"], dut_y, color=color, **eng.VHDL_STYLE)
        ax.plot(psim["t"], ref_y, color=color, **eng.REF_STYLE)
    ax.set_ylabel("Corrente [A]")
    ax.set_title("Correntes de fase")
    ax.legend(handles=handles, loc="best", fontsize=8, framealpha=0.9)

    ax = axes[1]
    ax.plot(fpga["t"], fpga["speed"], color=eng.COL_VHDL, **eng.VHDL_STYLE)
    ax.plot(psim["t"], psim["speed"], color=eng.COL_C, **eng.REF_STYLE)
    ax.set_ylabel(r"$\omega_{mec}$ [rad/s]")
    ax.set_xlabel("Tempo [s]")

    for a, b, _label, col in wins:
        for panel in axes:
            panel.axvspan(a, b, color=col, alpha=0.13)

    fig.tight_layout()
    eng.save_fig(fig, out_dir, f"{case['fig_prefix']}_{case['id']}_Overview")


_L4B_LABELS = {"dut": "FPGA (real)", "ref": "PSIM (independente)"}

CASES_L4B = [
    {"id": "S0", "dir": "S0_l4", "label": "S0 — t$_{acc}$=1 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/S0/S0_1us_trapezoidal.csv", "labels": _L4B_LABELS},
    {"id": "A1", "dir": "A1_l4", "label": "A1 — t$_{acc}$=0,5 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A1_1us.csv", "labels": _L4B_LABELS},
    {"id": "A3", "dir": "A3_l4", "label": "A3 — t$_{acc}$=1 s, carga leve", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A3_1us.csv", "labels": _L4B_LABELS},
    {"id": "A5", "dir": "A5_l4", "label": "A5 — t$_{acc}$=5 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A5_1us.csv", "labels": _L4B_LABELS},
    {"id": "B1", "dir": "B1_l4", "label": "B1 — degrau 0,25→0,75 T$_n$", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/BX/B1_500ns.csv", "labels": _L4B_LABELS},
    {"id": "B2", "dir": "B2_l4", "label": "B2 — degrau 0,50→1,00 T$_n$", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/BX/B2_500ns.csv", "labels": _L4B_LABELS},
]


def generate_case_l4b(case: dict, out_dir: Path, campaign: Path, repo_root: Path) -> dict:
    metrics: dict[str, dict] = {}
    plot_full_overview_l4b(case, out_dir, campaign, repo_root)
    for seg in ("partida", "regime"):
        npz_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / f"{seg}.npz"
        if not npz_path.is_file():
            continue
        t_ms, data = load_l4b_segment(case, seg, campaign)
        seg_case = _seg_case(case, seg)
        plot_overlay_l4b(t_ms, data, seg_case, out_dir)
        eng.plot_lissajous(t_ms, data, seg_case, out_dir)
        eng.plot_residual(t_ms, data, seg_case, out_dir)
        metrics[seg] = compute_metrics_l4b(data)
    print(f"[ok] {case['id']}: figuras L4-B em {out_dir}")
    return metrics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gera figuras L4-B (FPGA real vs PSIM independente).")
    ap.add_argument("--campaign", type=Path,
                     default=eng.REPO_ROOT / "verification/results/2026-07-25_campaign_l4_final")
    ap.add_argument("--out", type=Path,
                     default=eng.REPO_ROOT / "docs/results-chapter/figures/l4b")
    ap.add_argument("--tables-out", type=Path,
                     default=eng.REPO_ROOT / "docs/results-chapter/tables")
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES_L4B],
                     help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES_L4B if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = generate_case_l4b(case, args.out, args.campaign, eng.REPO_ROOT)

    args.tables_out.mkdir(parents=True, exist_ok=True)
    (args.tables_out / "l4b_metricas.tex").write_text(render_l4b_table(all_metrics), encoding="utf-8")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l4b_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"Tabela gerada em {args.tables_out / 'l4b_metricas.tex'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
