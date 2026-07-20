#!/usr/bin/env python3
"""Gera as figuras L4 (FPGA real vs modelo C), dirigido por caso.

Fonte: capturas .hilbin reais de bancada, já processadas por `hilbin_vs_c.py`
para .npz alinhados (fpga_* vs cmod_*), em dois segmentos: `partida` e `regime`.
Reutiliza o engine de `l2_figures.py` mapeando as correntes de fase (ia, ib) e o
fluxo/velocidade para as chaves canônicas vhdl_*/ref_*.

Uso (de verification/cocotb/):
    uv run python scripts/l4_figures.py
    uv run python scripts/l4_figures.py --case S0 --case B1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import l2_figures as eng

CAMPAIGN_L4 = eng.REPO_ROOT / "verification/results/2026-07-14_campaign_l4"
DEFAULT_OUT = eng.REPO_ROOT / "docs/results-chapter/figures/l4"

_LAB = {"dut": "FPGA (real)", "ref": "Modelo C"}
_SEG_NAME = {"partida": "Partida", "regime": "Regime"}
SEGMENTS = ("partida", "regime")

CASES_L4 = [
    {"id": "S0", "dir": "S0_l4", "label": "S0 — t$_{acc}$=1 s, vazio"},
    {"id": "A1", "dir": "A1_l4", "label": "A1 — t$_{acc}$=0,5 s, vazio"},
    {"id": "A3", "dir": "A3_l4", "label": "A3 — t$_{acc}$=1 s, carga leve"},
    {"id": "A5", "dir": "A5_l4", "label": "A5 — t$_{acc}$=5 s, vazio"},
    {"id": "B1", "dir": "B1_l4", "label": "B1 — degrau 0,25→0,75 T$_n$"},
    {"id": "B2", "dir": "B2_l4", "label": "B2 — degrau 0,50→1,00 T$_n$"},
]


def _npz_path(case: dict, seg: str, campaign: Path) -> Path:
    return campaign / case["dir"] / "l4_pwm_replay/capture" / f"{seg}.npz"


def load_segment(case: dict, seg: str, campaign: Path = CAMPAIGN_L4) -> tuple[np.ndarray, dict]:
    """Carrega o .npz de um segmento e mapeia p/ as chaves canônicas do engine.

    Correntes vêm em fase (ia, ib); reconstroi α/β por Clarke direta para que os
    plots do engine (que fazem Clarke inversa) reproduzam ia/ib/ic corretamente.
    Fluxo já vem em α/β (flux_a/flux_b).
    """
    d = np.load(_npz_path(case, seg, campaign))
    s3 = np.sqrt(3.0)

    def clarke_beta(ia, ib):
        return (np.asarray(ia) + 2.0 * np.asarray(ib)) / s3

    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"]),
        "vhdl_i_beta": clarke_beta(d["fpga_ia"], d["fpga_ib"]),
        "ref_i_alpha": np.asarray(d["cmod_ia"]),
        "ref_i_beta": clarke_beta(d["cmod_ia"], d["cmod_ib"]),
        "vhdl_flux_alpha": np.asarray(d["fpga_flux_a"]),
        "vhdl_flux_beta": np.asarray(d["fpga_flux_b"]),
        "ref_flux_alpha": np.asarray(d["cmod_flux_a"]),
        "ref_flux_beta": np.asarray(d["cmod_flux_b"]),
        "vhdl_speed": np.asarray(d["fpga_speed"]),
        "ref_speed": np.asarray(d["cmod_speed"]),
    }
    t_ms = np.asarray(d["fpga_t"], dtype=float) * 1000.0
    return t_ms, data


def _seg_case(case: dict, seg: str) -> dict:
    return {"id": case["id"], "tipo": "vf", "fig_prefix": "HIL_L4", "labels": _LAB,
            "fig_id": f"{case['id']}_{_SEG_NAME[seg]}",
            "label": f"{case['label']} · {_SEG_NAME[seg]}"}


def generate_case_l4(case: dict, out_dir: Path, campaign: Path = CAMPAIGN_L4) -> dict:
    metrics: dict[str, dict] = {}
    # visão geral do tempo todo (FPGA real) antes dos zooms
    if (campaign / case["dir"] / "raw/capture.hilbin").is_file():
        plot_full_overview(case, out_dir, campaign)
    for seg in SEGMENTS:
        if not _npz_path(case, seg, campaign).is_file():
            continue
        t_ms, data = load_segment(case, seg, campaign)
        c = _seg_case(case, seg)
        eng.plot_overlay(t_ms, data, c, out_dir)
        eng.plot_residual(t_ms, data, c, out_dir)
        if seg == "regime":
            eng.plot_lissajous(t_ms, data, c, out_dir)  # trajetória real vs C
        metrics[seg] = eng.compute_metrics(data)
    print(f"[ok] {case['id']}: figuras L4 em {out_dir}")
    return metrics


def _load_full_fpga(case: dict, campaign: Path) -> dict:
    """Trajetória FPGA completa (todo o segmento monotônico) direto do .hilbin.

    Só faz parsing do binário (rápido, ~0,03 s); NÃO replaya o modelo C — a
    comparação detalhada fica nos zooms partida/regime.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hilbin_vs_c as H
    _, fpga, _ = H.parse_hilbin(campaign / case["dir"] / "raw/capture.hilbin")
    return H._clip_fpga(fpga)


def plot_full_overview(case: dict, out_dir: Path, campaign: Path = CAMPAIGN_L4) -> None:
    """Visão geral da captura inteira (FPGA real), com as janelas partida/regime
    sombreadas — contexto para o leitor antes dos zooms."""
    fpga = _load_full_fpga(case, campaign)
    n = fpga["t"].size
    sl = slice(None, None, max(1, n // 4000))
    t = fpga["t"][sl]
    ia, ib = fpga["ia"][sl], fpga["ib"][sl]
    ic = -(ia + ib)
    flux = np.sqrt(fpga["flux_a"][sl] ** 2 + fpga["flux_b"][sl] ** 2)
    spd = fpga["speed"][sl]

    # janelas dos zooms (para sombrear), lidas do metrics.json
    wins = []
    mj_path = campaign / case["dir"] / "l4_pwm_replay/capture/metrics.json"
    if mj_path.is_file():
        mj = json.loads(mj_path.read_text())
        for lbl, col in (("partida", eng.PHASE_COLORS[0]), ("regime", eng.PHASE_COLORS[2])):
            w = mj.get(lbl, {}).get("window_s")
            if w:
                wins.append((w[0], w[1], _SEG_NAME[lbl], col))

    plt = eng.plt
    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    for k, (y, lbl) in enumerate(((ia, "$i_a$"), (ib, "$i_b$"), (ic, "$i_c$"))):
        axes[0].plot(t, y, color=eng.PHASE_COLORS[k], linewidth=0.7, label=lbl)
    axes[0].set_ylabel("Corrente [A]")
    axes[0].set_title(f"L4 — {case['label']}: visão geral da captura (FPGA real)")
    axes[1].plot(t, flux, color=eng.COL_VHDL, linewidth=0.9)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, spd, color=eng.COL_VHDL, linewidth=0.9)
    axes[2].set_ylabel(r"$\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")

    for (a, b, lbl, col) in wins:
        for ax in axes:
            ax.axvspan(a, b, color=col, alpha=0.13)
        axes[0].axvspan(a, b, color=col, alpha=0.13, label=lbl)
    axes[0].legend(loc="upper right", ncol=5, fontsize=7.5)
    eng.save_fig(fig, out_dir, f"HIL_L4_{case['id']}_Overview")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Gera figuras L4 (FPGA real vs C).")
    ap.add_argument("--campaign", type=Path, default=CAMPAIGN_L4)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES_L4],
                    help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES_L4 if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = generate_case_l4(case, args.out, args.campaign)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l4_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"[ok] metricas em {args.out / 'l4_metrics.json'}")


if __name__ == "__main__":
    main()
