#!/usr/bin/env python3
"""Gera as figuras L2 (solver VHDL vs modelo C), dirigido por caso.

Uso (de verification/cocotb/):
    uv run python scripts/l2_figures.py                 # 3 casos S0 padrao
    uv run python scripts/l2_figures.py --case sine
    uv run python scripts/l2_figures.py --campaign ../results/... --out /tmp/figs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_common as cc  # noqa: E402  (load_csv_columns, inverse_clarke)

plt.rcParams.update({
    "font.family": "serif",
    "axes.grid": True,
    "grid.color": "#d9d9d9",
    "grid.linewidth": 0.5,
    "axes.edgecolor": "black",
    "figure.dpi": 120,
})

# Paleta Okabe-Ito (segura para daltonismo; validada com dataviz).
# Fases: VHDL solido, C tracejado.
PHASE_COLORS = ("#0072B2", "#E69F00", "#009E73")  # ia, ib, ic
COL_VHDL = "#0072B2"        # azul  — solido
COL_C = "#D55E00"           # vermillion — tracejado
COL_ERR_SPEED = "#CC79A7"   # roxo avermelhado (erro de velocidade)
# VHDL grosso semitransparente por baixo; C tracejado fino por cima (estilo L1):
# assim, mesmo com sobreposicao quase perfeita, ambos ficam visiveis.
VHDL_STYLE = {"linestyle": "-", "linewidth": 2.4, "alpha": 0.5}
REF_STYLE = {"linestyle": "--", "linewidth": 1.1, "alpha": 0.95}

# ── Caminhos ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_DIR = REPO_ROOT / "verification/results/2026-07-04_campaign_03/S0_tacc1s_load000"
DEFAULT_OUT = REPO_ROOT / "docs/results-chapter/figures/l2"

# ── Manifesto dos casos ───────────────────────────────────────────────────────
# tipo: "sine" (regime) ou "vf" (rampa). Define o conjunto de plots.
CASES = [
    {"id": "sine",  "dir": "l2_sine_60hz_realts", "csv": "sine_vhdl_vs_c.csv",
     "tipo": "sine", "label": "Partida senoidal 60 Hz",
     # 50 ms de partida do repouso sob senoide: NAO e regime permanente.
     # Zoom nos ultimos ~1.5 ciclos, onde a corrente ja esta mais desenvolvida.
     "zoom": [(30.0, 50.0, "Detalhe de fase", "#009E73")]},   # ms (ver t_ms)
    {"id": "vf50ms", "dir": "l2_vf_50ms_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 50 ms",
     "plots": ["overlay", "residual"],   # override: transitorio curto
     "zoom": []},
    {"id": "vf2s", "dir": "l2_vf_2s_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 2 s",
     "zoom": [(1900.0, 2000.0, "Regime permanente", "#009E73")],  # ms
     "windows_s": [(0.0, 0.05), (0.05, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]},
]

CSV_COLS = ["t_us",
            "vhdl_i_alpha", "vhdl_i_beta", "ref_i_alpha", "ref_i_beta",
            "vhdl_flux_alpha", "vhdl_flux_beta", "ref_flux_alpha", "ref_flux_beta",
            "vhdl_speed", "ref_speed"]

RAD_S_TO_RPM = 60.0 / (2.0 * np.pi)


# ── Métricas ──────────────────────────────────────────────────────────────────
def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


def _nrmse(ref: np.ndarray, vhdl: np.ndarray) -> float:
    denom = _rms(ref)
    return float(_rms(vhdl - ref) / denom) if denom > 1e-12 else float("nan")


def _r2(ref: np.ndarray, vhdl: np.ndarray) -> float:
    ss_res = float(np.sum((vhdl - ref) ** 2))
    ss_tot = float(np.sum((ref - np.mean(ref)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")


def _max_abs(ref: np.ndarray, vhdl: np.ndarray) -> float:
    return float(np.max(np.abs(vhdl - ref)))


def _mae(ref: np.ndarray, vhdl: np.ndarray) -> float:
    return float(np.mean(np.abs(vhdl - ref)))


def compute_metrics(data: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Recalcula NRMSE/R2/erro-max/MAE por sinal a partir das colunas do CSV."""
    def arr(k):
        return np.asarray(data[k], dtype=float)

    out: dict[str, dict[str, float]] = {}
    for sig in ("i_alpha", "i_beta"):
        ref, vhdl = arr(f"ref_{sig}"), arr(f"vhdl_{sig}")
        out[sig] = {"nrmse": _nrmse(ref, vhdl), "r2": _r2(ref, vhdl),
                    "max_abs": _max_abs(ref, vhdl)}
    for sig in ("flux_alpha", "flux_beta"):
        ref, vhdl = arr(f"ref_{sig}"), arr(f"vhdl_{sig}")
        out[sig] = {"mae": _mae(ref, vhdl), "r2": _r2(ref, vhdl),
                    "max_abs": _max_abs(ref, vhdl)}
    ref, vhdl = arr("ref_speed"), arr("vhdl_speed")
    out["speed"] = {"mae": _mae(ref, vhdl), "mae_rpm": _mae(ref, vhdl) * RAD_S_TO_RPM,
                    "r2": _r2(ref, vhdl), "max_abs": _max_abs(ref, vhdl)}
    return out


# ── Carregamento / gravação ───────────────────────────────────────────────────
def _fig_id(case: dict) -> str:
    if "fig_id" in case:
        return case["fig_id"]
    return {"sine": "Sine", "vf50ms": "VF50ms", "vf2s": "VF2s",
            "sine6ms": "Sine6ms"}.get(
        case["id"], case["id"].capitalize())


def _fig_name(case: dict, kind: str) -> str:
    """Nome-base do arquivo: HIL_<nivel>_<Cenario>_<Tipo> (nivel default L2)."""
    return f"{case.get('fig_prefix', 'HIL_L2')}_{_fig_id(case)}_{kind}"


def _labels(case: dict) -> tuple[str, str]:
    """Rotulos (DUT, referencia) para legendas/titulos. Default VHDL vs C."""
    lab = case.get("labels", {})
    return lab.get("dut", "VHDL"), lab.get("ref", "C")


def _lvl(case: dict) -> str:
    """Prefixo de nivel para titulos: 'L2', 'L3', ... (de fig_prefix)."""
    return case.get("fig_prefix", "HIL_L2").replace("HIL_", "")


_SIGS = ("i_alpha", "i_beta", "flux_alpha", "flux_beta", "speed")
_TIME_SCALE_MS = {"t_us": 1e-3, "t_s": 1e3}


def load_case(case: dict, campaign: Path = CAMPAIGN_DIR) -> tuple[np.ndarray, dict]:
    """Carrega o CSV do caso e devolve (t_ms, data) com colunas canonicas.

    Aceita colunas de tempo distintas (`t_us` no L2, `t_s` no L3) e prefixos de
    referencia distintos (`ref_` no L2/PWM-replay, `c_` no full-stack L3),
    remapeando tudo para as chaves canonicas `vhdl_*`/`ref_*`.
    """
    time_col = case.get("time_col", "t_us")
    ref_prefix = case.get("ref_prefix", "ref")
    extra = list(case.get("extra_cols", []))

    cols = [time_col]
    cols += [f"vhdl_{s}" for s in _SIGS]
    cols += [f"{ref_prefix}_{s}" for s in _SIGS]
    cols += [c for c in extra if c not in cols]

    csv_path = campaign / case["dir"] / case["csv"]
    raw = cc.load_csv_columns(csv_path, cols)

    data: dict[str, list[float]] = {}
    for s in _SIGS:
        data[f"vhdl_{s}"] = raw[f"vhdl_{s}"]
        data[f"ref_{s}"] = raw[f"{ref_prefix}_{s}"]
    for c in extra:
        data[c] = raw[c]

    t_ms = np.asarray(raw[time_col], dtype=float) * _TIME_SCALE_MS[time_col]
    return t_ms, data


def save_fig(fig, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


# ── Plots ─────────────────────────────────────────────────────────────────────
def plot_overlay(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """3 paineis: correntes trifasicas, modulo do fluxo, velocidade (DUT vs ref)."""
    dut, ref = _labels(case)
    t = t_ms / 1000.0  # s
    vhdl_i = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_i = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])

    def mag(a, b):
        a, b = np.asarray(a), np.asarray(b)
        return np.sqrt(a ** 2 + b ** 2)

    vhdl_flux = mag(data["vhdl_flux_alpha"], data["vhdl_flux_beta"])
    ref_flux = mag(data["ref_flux_alpha"], data["ref_flux_beta"])

    fig, axes = plt.subplots(3, 1, figsize=(7, 8), sharex=True)

    labels = ("$i_a$", "$i_b$", "$i_c$")
    for k in range(3):
        axes[0].plot(t, vhdl_i[k], color=PHASE_COLORS[k], label=labels[k], **VHDL_STYLE)
        axes[0].plot(t, ref_i[k], color=PHASE_COLORS[k], **REF_STYLE)
    axes[0].set_ylabel("Corrente [A]")
    axes[0].set_title(f"{_lvl(case)} — {case['label']}: correntes (— {dut}, - - {ref})")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    axes[1].plot(t, vhdl_flux, color=COL_VHDL, **VHDL_STYLE, label=dut)
    axes[1].plot(t, ref_flux, color=COL_C, **REF_STYLE, label=ref)
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(t, np.asarray(data["vhdl_speed"]), color=COL_VHDL, **VHDL_STYLE, label=dut)
    axes[2].plot(t, np.asarray(data["ref_speed"]), color=COL_C, **REF_STYLE, label=ref)
    axes[2].set_ylabel(r"$\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].legend(loc="upper right", fontsize=8)

    save_fig(fig, out_dir, _fig_name(case, "Overlay"))


def _subsample(n: int, target: int = 5000) -> slice:
    step = max(1, n // target)
    return slice(None, None, step)


def plot_lissajous(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Trajetoria espaco-vetorial i_beta x i_alpha (DUT vs ref)."""
    dut, ref = _labels(case)
    s = _subsample(len(t_ms))
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(np.asarray(data["vhdl_i_alpha"])[s], np.asarray(data["vhdl_i_beta"])[s],
            color=COL_VHDL, label=dut, **VHDL_STYLE)
    ax.plot(np.asarray(data["ref_i_alpha"])[s], np.asarray(data["ref_i_beta"])[s],
            color=COL_C, label=ref, **REF_STYLE)
    ax.set_xlabel(r"$i_\alpha$ [A]")
    ax.set_ylabel(r"$i_\beta$ [A]")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(f"{_lvl(case)} — {case['label']}: trajetória $i_\\beta \\times i_\\alpha$")
    ax.legend(loc="upper right", fontsize=9)
    save_fig(fig, out_dir, _fig_name(case, "Lissajous"))


def plot_phase_zoom(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Corrente ia completa + regioes sombreadas + paineis de zoom (estilo L1)."""
    t = t_ms / 1000.0  # s
    vhdl_ia = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0]
    ref_ia = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0]
    vhdl_ia, ref_ia = np.asarray(vhdl_ia), np.asarray(ref_ia)

    dut, ref = _labels(case)
    zooms = case.get("zoom", [])
    nz = len(zooms)
    fig, axes = plt.subplots(1 + nz, 1, figsize=(8, 3 + 2.2 * nz))
    if nz == 0:
        axes = [axes]
    top = axes[0]
    top.plot(t, vhdl_ia, color=COL_VHDL, label=f"$i_a$ ({dut})", **VHDL_STYLE)
    top.plot(t, ref_ia, color=COL_C, label=f"$i_a$ ({ref})", **REF_STYLE)
    for (a_ms, b_ms, lbl, col) in zooms:
        top.axvspan(a_ms / 1000.0, b_ms / 1000.0, color=col, alpha=0.15, label=lbl)
    top.set_ylabel("$i_a$ [A]")
    top.set_xlabel("Tempo [s]")
    top.set_title(f"{_lvl(case)} — {case['label']}: visão completa e zoom")
    top.legend(loc="upper right", fontsize=8)

    for ax, (a_ms, b_ms, lbl, col) in zip(axes[1:], zooms):
        a, b = a_ms / 1000.0, b_ms / 1000.0
        mask = (t >= a) & (t <= b)
        ax.plot(t[mask], vhdl_ia[mask], color=COL_VHDL, label=dut, **VHDL_STYLE)
        ax.plot(t[mask], ref_ia[mask], color=COL_C, label=ref, **REF_STYLE)
        ax.set_title(f"{lbl}: {a_ms:.0f}–{b_ms:.0f} ms", fontsize=10)
        ax.set_ylabel("$i_a$ [A]")
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("Tempo [s]")
    fig.tight_layout()
    save_fig(fig, out_dir, _fig_name(case, "PhaseZoom"))


def plot_residual(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Traco de erro epsilon(t)=VHDL-C: correntes de fase e velocidade."""
    t = t_ms / 1000.0
    vhdl_i = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_i = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])
    labels = ("$\\varepsilon_{i_a}$", "$\\varepsilon_{i_b}$", "$\\varepsilon_{i_c}$")

    fig, axes = plt.subplots(2, 1, figsize=(7, 5), sharex=True)
    for k in range(3):
        err = np.asarray(vhdl_i[k]) - np.asarray(ref_i[k])
        axes[0].plot(t, err, color=PHASE_COLORS[k], linewidth=0.9, label=labels[k])
    axes[0].axhline(0.0, color="0.5", linewidth=0.6)
    axes[0].set_ylabel("Erro corrente [A]")
    dut, ref = _labels(case)
    axes[0].set_title(f"{_lvl(case)} — {case['label']}: erro {dut} − {ref}")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    err_w = np.asarray(data["vhdl_speed"]) - np.asarray(data["ref_speed"])
    axes[1].plot(t, err_w, color=COL_ERR_SPEED, linewidth=1.0, label=r"$\varepsilon_\omega$")
    axes[1].axhline(0.0, color="0.5", linewidth=0.6)
    axes[1].set_ylabel("Erro veloc. [rad/s]")
    axes[1].set_xlabel("Tempo [s]")
    axes[1].legend(loc="upper right", fontsize=8)
    save_fig(fig, out_dir, _fig_name(case, "Residual"))


def plot_window_nrmse(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """NRMSE de i_alpha/i_beta por janela temporal (barras)."""
    t_s = t_ms / 1000.0
    windows = case.get("windows_s", [])
    ia_ref, ia_vhdl = np.asarray(data["ref_i_alpha"]), np.asarray(data["vhdl_i_alpha"])
    ib_ref, ib_vhdl = np.asarray(data["ref_i_beta"]), np.asarray(data["vhdl_i_beta"])

    nrmse_a, nrmse_b, xlabels = [], [], []
    for (a, b) in windows:
        m = (t_s >= a) & (t_s < b)
        if not np.any(m):
            nrmse_a.append(0.0); nrmse_b.append(0.0)
        else:
            nrmse_a.append(_nrmse(ia_ref[m], ia_vhdl[m]) * 100.0)
            nrmse_b.append(_nrmse(ib_ref[m], ib_vhdl[m]) * 100.0)
        xlabels.append(f"{a:g}–{b:g}")

    x = np.arange(len(windows))
    w = 0.4
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - w / 2, nrmse_a, w, color=PHASE_COLORS[0], label=r"$i_\alpha$")
    ax.bar(x + w / 2, nrmse_b, w, color=PHASE_COLORS[1], label=r"$i_\beta$")
    ax.set_xticks(x); ax.set_xticklabels(xlabels)
    ax.set_xlabel("Janela [s]")
    ax.set_ylabel("NRMSE [%]")
    ax.set_title(f"{_lvl(case)} — {case['label']}: NRMSE por janela")
    ax.legend(fontsize=9)
    save_fig(fig, out_dir, _fig_name(case, "WindowNRMSE"))


def plot_pwm_stimulus(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Estimulo PWM/tensao: tensoes de fase va/vb/vc (saida NPC) numa janela curta.

    Especifico do L3 — mostra a modulacao NPC real que alimenta os dois modelos.
    A janela vem de case['pwm_zoom_ms']=(t0,t1); sem ela, usa os primeiros 20 ms.
    """
    t = np.asarray(t_ms)
    a_ms, b_ms = case.get("pwm_zoom_ms", (float(t.min()), min(float(t.min()) + 20.0, float(t.max()))))
    mask = (t >= a_ms) & (t <= b_ms)
    ts = t[mask] / 1000.0  # s

    fig, ax = plt.subplots(figsize=(8, 3.5))
    for name, col, lbl in (("va", PHASE_COLORS[0], "$v_a$"),
                           ("vb", PHASE_COLORS[1], "$v_b$"),
                           ("vc", PHASE_COLORS[2], "$v_c$")):
        v = np.asarray(data[name])[mask]
        ax.plot(ts, v, color=col, linewidth=1.0, drawstyle="steps-post", label=lbl)
    ax.set_xlabel("Tempo [s]")
    ax.set_ylabel("Tensão de fase [V]")
    ax.set_title(f"{_lvl(case)} — {case['label']}: estímulo PWM (saída NPC), "
                 f"{a_ms:.0f}–{b_ms:.0f} ms")
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    save_fig(fig, out_dir, _fig_name(case, "PWMStimulus"))


# ── Driver ────────────────────────────────────────────────────────────────────
# Conjunto de plots por tipo de cenario
PLOTSET = {
    "sine": ("overlay", "lissajous", "phase_zoom"),
    "vf": ("overlay", "lissajous", "residual", "phase_zoom", "window_nrmse"),
}
_PLOT_FN = {
    "overlay": lambda t, d, c, o: plot_overlay(t, d, c, o),
    "lissajous": lambda t, d, c, o: plot_lissajous(t, d, c, o),
    "phase_zoom": lambda t, d, c, o: plot_phase_zoom(t, d, c, o),
    "residual": lambda t, d, c, o: plot_residual(t, d, c, o),
    "window_nrmse": lambda t, d, c, o: plot_window_nrmse(t, d, c, o),
    "pwm_stimulus": lambda t, d, c, o: plot_pwm_stimulus(t, d, c, o),
}


def generate_case(case: dict, out_dir: Path, campaign: Path = CAMPAIGN_DIR) -> dict:
    t_ms, data = load_case(case, campaign)
    metrics = compute_metrics(data)
    kinds = case.get("plots") or PLOTSET[case["tipo"]]
    for kind in kinds:
        if kind == "phase_zoom" and not case.get("zoom"):
            continue
        if kind == "window_nrmse" and not case.get("windows_s"):
            continue
        _PLOT_FN[kind](t_ms, data, case, out_dir)
    print(f"[ok] {case['id']}: figuras em {out_dir}")
    return metrics


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Gera figuras L2 (VHDL vs C).")
    ap.add_argument("--campaign", type=Path, default=CAMPAIGN_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES],
                    help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = generate_case(case, args.out, args.campaign)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l2_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"[ok] metricas em {args.out / 'l2_metrics.json'}")


if __name__ == "__main__":
    main()
