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

    A telemetria da placa já entrega as correntes em α/β (campos `ialpha_A`/
    `ibeta_A`, gravados no .hilbin como `ia`/`ib` — ver hilbin_vs_c.py, onde
    `s["ia"]`→`is_alpha` e `s["ib"]`→`is_beta`). Portanto o mapeamento é direto,
    SEM Clarke: os plots do engine (que fazem Clarke inversa) reconstroem
    ia/ib/ic equilibradas a partir do α/β real. Fluxo idem (flux_a/flux_b = α/β).
    """
    d = np.load(_npz_path(case, seg, campaign))

    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"]),
        "vhdl_i_beta": np.asarray(d["fpga_ib"]),
        "ref_i_alpha": np.asarray(d["cmod_ia"]),
        "ref_i_beta": np.asarray(d["cmod_ib"]),
        "vhdl_flux_alpha": np.asarray(d["fpga_flux_a"]),
        "vhdl_flux_beta": np.asarray(d["fpga_flux_b"]),
        "ref_flux_alpha": np.asarray(d["cmod_flux_a"]),
        "ref_flux_beta": np.asarray(d["cmod_flux_b"]),
        "vhdl_speed": np.asarray(d["fpga_speed"]),
        "ref_speed": np.asarray(d["cmod_speed"]),
    }
    t_ms = np.asarray(d["fpga_t"], dtype=float) * 1000.0
    return t_ms, data


def _seg_case(case: dict, seg: str, tload_step: tuple | None = None) -> dict:
    c = {"id": case["id"], "tipo": "vf", "fig_prefix": "HIL_L4", "labels": _LAB,
         "fig_id": f"{case['id']}_{_SEG_NAME[seg]}",
         "label": f"{case['label']} · {_SEG_NAME[seg]}"}
    if tload_step:
        c["tload_step"] = tload_step
    return c


def _read_tload_step(case: dict, campaign: Path) -> tuple | None:
    """Lê (pre_nm, post_nm, t_step_s) do metrics.json do caso, quando é um
    degrau de carga (Grupo B). None para os demais (S0/A1/A3/A5, carga
    constante) -- aí o overlay fica com os 3 painéis de sempre."""
    mj_path = campaign / case["dir"] / "l4_pwm_replay/capture/metrics.json"
    if not mj_path.is_file():
        return None
    tload = json.loads(mj_path.read_text()).get("tload")
    if isinstance(tload, dict) and "t_step_s" in tload:
        return (tload["pre"], tload["post"], tload["t_step_s"])
    return None


def generate_case_l4(case: dict, out_dir: Path, campaign: Path = CAMPAIGN_L4) -> dict:
    metrics: dict[str, dict] = {}
    tload_step = _read_tload_step(case, campaign)
    # visão geral do tempo todo (FPGA real) antes dos zooms
    if (campaign / case["dir"] / "raw/capture.hilbin").is_file():
        plot_full_overview(case, out_dir, campaign)
    for seg in SEGMENTS:
        if not _npz_path(case, seg, campaign).is_file():
            continue
        t_ms, data = load_segment(case, seg, campaign)
        c = _seg_case(case, seg, tload_step)
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
    # fpga["ia"]/["ib"] são, na verdade, i_alpha/i_beta (telemetria α/β da placa);
    # reconstrói as três fases físicas por Clarke inversa.
    i_alpha, i_beta = fpga["ia"][sl], fpga["ib"][sl]
    ia, ib, ic = (np.asarray(x) for x in eng.cc.inverse_clarke(i_alpha, i_beta))
    flux = np.sqrt(fpga["flux_a"][sl] ** 2 + fpga["flux_b"][sl] ** 2)
    spd = fpga["speed"][sl]

    # janelas dos zooms (para sombrear), lidas do metrics.json
    wins = []
    step_t = None
    mj_path = campaign / case["dir"] / "l4_pwm_replay/capture/metrics.json"
    if mj_path.is_file():
        mj = json.loads(mj_path.read_text())
        tload = mj.get("tload")
        # Grupo B (degrau): "partida"/"regime" aqui são, na verdade, as janelas
        # de regime estacionário imediatamente antes/depois do degrau (ver
        # hilbin_vs_c.py:685-688) — rótulo genérico confundiria com o
        # transitório de partida dos demais casos. Marca também o instante
        # exato do degrau com uma linha vertical, em vez de deixar implícito
        # na fronteira entre as duas sombras.
        is_step = isinstance(tload, dict) and "t_step_s" in tload
        seg_label = ({"partida": "Antes do degrau", "regime": "Depois do degrau"}
                     if is_step else _SEG_NAME)
        if is_step:
            step_t = tload["t_step_s"]
        for lbl, col in (("partida", eng.PHASE_COLORS[0]), ("regime", eng.PHASE_COLORS[2])):
            w = mj.get(lbl, {}).get("window_s")
            if w:
                wins.append((w[0], w[1], seg_label[lbl], col))

    plt = eng.plt
    n_rows = 4 if step_t is not None else 3
    fig, axes = plt.subplots(n_rows, 1, figsize=(8, 7 if n_rows == 3 else 8.6), sharex=True)
    for k, (y, lbl) in enumerate(((ia, "$i_a$"), (ib, "$i_b$"), (ic, "$i_c$"))):
        axes[0].plot(t, y, color=eng.PHASE_COLORS[k], linewidth=0.7, label=lbl)
    axes[0].set_ylabel("Corrente [A]")
    axes[0].set_title(f"L4 — {case['label']}: visão geral da captura (FPGA real)")
    axes[1].plot(t, flux, color=eng.COL_VHDL, linewidth=0.9)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[2].plot(t, spd, color=eng.COL_VHDL, linewidth=0.9)
    axes[2].set_ylabel(r"$\omega$ [rad/s]")

    if step_t is not None:
        pre_nm, post_nm = tload["pre"], tload["post"]
        tl = np.where(t >= step_t, post_nm, pre_nm)
        axes[3].plot(t, tl, color="black", linewidth=1.4, drawstyle="steps-post")
        axes[3].set_ylabel(r"$T_L$ [N$\cdot$m]")
        axes[3].margins(y=0.35)
        axes[3].annotate(f"{pre_nm:.1f} N·m", xy=(t[0], pre_nm),
                         xytext=(6, 6), textcoords="offset points", fontsize=8)
        axes[3].annotate(f"{post_nm:.1f} N·m", xy=(step_t, post_nm),
                         xytext=(6, 6), textcoords="offset points", fontsize=8)
    axes[-1].set_xlabel("Tempo [s]")

    for (a, b, lbl, col) in wins:
        for ax in axes:
            ax.axvspan(a, b, color=col, alpha=0.13)
        axes[0].axvspan(a, b, color=col, alpha=0.13, label=lbl)
    if step_t is not None:
        for ax in axes:
            ax.axvline(step_t, color="black", linestyle="--", linewidth=1.1)
        axes[0].axvline(step_t, color="black", linestyle="--", linewidth=1.1,
                        label=f"Degrau de carga (t={step_t:g} s)")
    axes[0].legend(loc="upper right", ncol=3, fontsize=7.5)
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
