#!/usr/bin/env python3
"""Funções de carga e construção de figura compartilhadas entre
results_explorer_app.py (explorer completo, uso local) e
results_presentation_app.py (versão curada, pública em /results).

Sem fluxo de página — só primitivas puras e dados estáticos (algumas
funções usam st.cache_data para evitar reler CSV/NPZ grandes ao trocar de
seleção na sidebar).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent))
import results_explorer_data as red

# Fundo claro (plotly_white) em vez de escuro -- depois de duas rodadas
# ajustando cor/largura pro fundo escuro sem o resultado ficar legível,
# fundo branco + cores saturadas escuras é a combinação clássica de maior
# contraste pra esse tipo de comparação. Paleta validada contra o surface
# claro (#ffffff) com dataviz:scripts/validate_palette.js -- contraste
# >=3:1 e separação CVD ok (worst-case só com secondary encoding, que já
# temos via dash no PSIM).
COLOR_BLUE = "#2a78d6"
COLOR_RED = "#e34948"
COLOR_GREEN = "#008300"
COLOR_ORANGE = "#eb6834"
COLOR_AQUA = "#1baf7a"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# Cap por série numa figura. Sem isso, janelas com PSIM mesclado (o PSIM
# simula num passo bem mais fino que a telemetria FPGA/C) chegam a ter
# 350 mil-1 milhão de pontos por canal -- o navegador não desenha isso
# rápido nem em WebGL. Decimação visual só, não afeta métricas (essas vêm
# de metrics.json, não do array plotado).
MAX_PLOT_POINTS = 6000


def _decimate(*arrays, max_pts: int = MAX_PLOT_POINTS):
    n = len(arrays[0])
    if n <= max_pts:
        return arrays
    step = max(1, n // max_pts)
    return tuple(a[::step] for a in arrays)


@st.cache_data
def load_csv(csv_path: str, mtime: float, columns: list[str]) -> pd.DataFrame:
    return pd.read_csv(csv_path, usecols=columns)


@st.cache_data
def load_npz(npz_path: str, mtime: float) -> dict:
    return red.load_npz_window(Path(npz_path))


def find_raw_hilbin(case_dir: Path) -> Path | None:
    """Localiza a captura .hilbin bruta de um caso L4 (varre subpastas)."""
    for cand in sorted(case_dir.rglob("*.hilbin")):
        return cand
    return None


@st.cache_data
def load_full_capture(hilbin_path: str, mtime: float, max_pts: int = MAX_PLOT_POINTS) -> dict:
    """Trajetória FPGA completa (todo o ensaio) direto do .hilbin, decimada.

    As correntes vêm do hardware em α/β (campos ia/ib); reconstrói as três
    fases por Clarke inversa, igual ao gerador da figura de visão geral.
    """
    import hilbin_vs_c as H  # noqa: E402
    import chapter_common as cc  # noqa: E402
    import numpy as _np

    _, fpga, _ = H.parse_hilbin(Path(hilbin_path))
    fpga = H._clip_fpga(fpga)
    n = fpga["t"].size
    step = max(1, n // max_pts)
    sl = slice(None, None, step)
    ia, ib, ic = cc.inverse_clarke(fpga["ia"][sl], fpga["ib"][sl])
    return {
        "t": _np.asarray(fpga["t"][sl], dtype=float),
        "ia": _np.asarray(ia, dtype=float),
        "ib": _np.asarray(ib, dtype=float),
        "ic": _np.asarray(ic, dtype=float),
        "flux": _np.sqrt(fpga["flux_a"][sl] ** 2 + fpga["flux_b"][sl] ** 2),
        "speed": _np.asarray(fpga["speed"][sl], dtype=float),
        "n_full": int(n),
    }


def build_full_capture_figure(d: dict) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        subplot_titles=["Correntes de fase [A]", "|ψ_r| [Wb]", "ω [rad/s]"],
    )
    for y, name, color in ((d["ia"], "i_a", COLOR_BLUE), (d["ib"], "i_b", COLOR_ORANGE),
                           (d["ic"], "i_c", COLOR_AQUA)):
        fig.add_trace(go.Scattergl(x=d["t"], y=y, name=name, line=dict(color=color, width=1)),
                      row=1, col=1)
    fig.add_trace(go.Scattergl(x=d["t"], y=d["flux"], name="|ψ_r|", line=dict(color=COLOR_BLUE)),
                  row=2, col=1)
    fig.add_trace(go.Scattergl(x=d["t"], y=d["speed"], name="ω", line=dict(color=COLOR_RED)),
                  row=3, col=1)
    fig.update_xaxes(title_text="Tempo (s)", row=3, col=1)
    fig.update_layout(height=760, showlegend=True, template="plotly_white", hovermode="x unified")
    return fig


# Suffixes are alpha/beta (Clarke, stationary frame), not phase a/b/c -- see
# NPZ_PREFIX_PAIR docstring. "ia"/"ib" is this project's pre-existing shorthand
# for i_alpha/i_beta (hilbin_vs_c.py:473,543); labeled here with the actual
# math symbol so the axis titles don't read as three-phase quantities.
SUFFIX_LABELS = {
    "ia": "iα [A]",
    "ib": "iβ [A]",
    "flux_a": "ψα [Wb]",
    "flux_b": "ψβ [Wb]",
    "speed": "ωmec [rad/s]",
}

# One fixed color per series, shared across every subplot, so the legend can
# be collapsed to exactly one entry per series instead of one per (series,
# suffix) pair.
#
# C (referência) desenhada larga + semi-transparente por baixo, FPGA fina +
# opaca por cima ("halo"): tentamos dash nas duas primeiro, mas quando FPGA
# segue C de perto (o caso bom -- validação passando) o tracejado fino em
# cima de um traço largo do mesmo tom vira uma mistura arroxeada ilegível
# em qualquer zoom com muita oscilação por pixel (dash squeezing). Sólido +
# opacidade não tem esse problema em nenhum zoom: contorno azul sempre visível
# nas bordas, e a cor de FPGA nunca se mistura porque ela é 100% opaca.
# PSIM mantém dash (pontilhado) -- diverge o bastante da dupla C/FPGA pra o
# problema não se repetir (ver screenshot de validação).
SERIES_STYLE = {
    "C (referência)": dict(color=_rgba(COLOR_BLUE, 0.55), width=4),
    "FPGA (real)": dict(color=COLOR_RED, width=1.6),
    "PSIM (motor nativo)": dict(color=COLOR_GREEN, dash="dot", width=1.4),
}


def build_npz_figure(data: dict, pairs: list[red.NpzChannelPair]) -> go.Figure:
    fig = make_subplots(
        rows=len(pairs), cols=1, shared_xaxes=True,
        subplot_titles=[SUFFIX_LABELS.get(p.suffix, p.suffix) for p in pairs],
    )
    legend_shown: set[str] = set()

    def add_series(row: int, x, y, name: str) -> None:
        x, y = _decimate(x, y)
        fig.add_trace(
            go.Scattergl(x=x, y=y, name=name, legendgroup=name,
                         showlegend=name not in legend_shown,
                         line=dict(**SERIES_STYLE[name])),
            row=row, col=1,
        )
        legend_shown.add(name)

    for i, pair in enumerate(pairs, start=1):
        add_series(i, data["cmod_t"], data[pair.cmod_key], "C (referência)")
        add_series(i, data["fpga_t"], data[pair.fpga_key], "FPGA (real)")
        if pair.psim_key is not None:
            add_series(i, data["psim_t"], data[pair.psim_key], "PSIM (motor nativo)")

    fig.update_layout(
        height=280 * len(pairs), showlegend=True, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Tempo (s)", row=len(pairs), col=1)
    return fig


KNOWN_WINDOW_LABELS = ("partida", "regime")

# ── Navegação amigável ──────────────────────────────────────────────────────
# Cada caso da matriz tem um identificador curto (S0, A1..A7, B1..B3). Aqui eles
# ganham nome legível, grupo e uma descrição do que o ensaio testa.
CASE_INFO: dict[str, dict[str, str]] = {
    "S0": {"grupo": "Sanidade", "nome": "S0 — partida a vazio (rampa 1 s)",
           "desc": "Caso de referência: motor parte do repouso até 60 Hz em 1 s, sem carga. "
                   "Usado para validar toda a cadeia antes da matriz."},
    "A1": {"grupo": "Partida e aceleração", "nome": "A1 — partida rápida, a vazio (rampa 0,5 s)",
           "desc": "Aceleração mais agressiva do conjunto (0→60 Hz em 0,5 s), sem carga."},
    "A2": {"grupo": "Partida e aceleração", "nome": "A2 — partida rápida, com carga (rampa 0,5 s)",
           "desc": "Rampa de 0,5 s com torque de carga nominal aplicado."},
    "A3": {"grupo": "Partida e aceleração", "nome": "A3 — partida com carga leve (rampa 1 s)",
           "desc": "Rampa de 1 s sob carga leve (0,5 T_n) — único caso do Grupo A com carga em L4."},
    "A4": {"grupo": "Partida e aceleração", "nome": "A4 — partida média, com carga (rampa 2 s)",
           "desc": "Rampa de 2 s com carga nominal."},
    "A5": {"grupo": "Partida e aceleração", "nome": "A5 — partida lenta, a vazio (rampa 5 s)",
           "desc": "Transitório de partida mais longo da matriz (0→60 Hz em 5 s), sem carga. "
                   "É a captura que expõe o regime estacionário mais claramente ao fim da rampa."},
    "A6": {"grupo": "Partida e aceleração", "nome": "A6 — partida lenta, com carga (rampa 5 s)",
           "desc": "Rampa de 5 s sob carga nominal."},
    "A7": {"grupo": "Partida e aceleração", "nome": "A7 — partida média, sobrecarga (rampa 2 s)",
           "desc": "Rampa de 2 s sob carga acima da nominal (1,1 T_n)."},
    "B1": {"grupo": "Perturbação de carga", "nome": "B1 — degrau de carga 0,25 → 0,75 T_n",
           "desc": "Motor em regime recebe um degrau de torque de carga em t=0,6 s. "
                   "Testa a resposta dinâmica (queda de velocidade, pico de corrente, recuperação)."},
    "B2": {"grupo": "Perturbação de carga", "nome": "B2 — degrau de carga 0,50 → 1,00 T_n",
           "desc": "Degrau de carga até o nominal — a perturbação mais severa da matriz."},
    "B3": {"grupo": "Perturbação de carga", "nome": "B3 — degrau de carga 0,75 → 0,25 T_n (alívio)",
           "desc": "Degrau de alívio de carga (excluído da análise formal por não atender à precondição de regime)."},
}
GROUP_ORDER = ["Sanidade", "Partida e aceleração", "Perturbação de carga"]


def case_id(case_dir: Path) -> str:
    """Extrai o identificador curto (S0, A5, B2...) do nome da pasta do caso."""
    return case_dir.name.split("_")[0].upper()


def case_label(case_dir: Path) -> str:
    info = CASE_INFO.get(case_id(case_dir))
    return info["nome"] if info else case_dir.name


def flatten_metrics(metrics: dict) -> pd.DataFrame:
    """L4 metrics.json nests per-window blocks (partida/regime, each a dict of
    scalar metrics) alongside run-level scalars/dicts (params, vdc, ...).
    Flatten only the known window blocks into (janela, métrica, valor) rows;
    everything else falls back to the flat métrica/valor view."""
    import json

    windows = {k: metrics[k] for k in KNOWN_WINDOW_LABELS if isinstance(metrics.get(k), dict)}
    if not windows:
        return pd.DataFrame(metrics.items(), columns=["métrica", "valor"])
    rows = []
    for window, block in windows.items():
        for key, value in block.items():
            if isinstance(value, dict):
                value = json.dumps(value)
            rows.append((window, key, value))
    return pd.DataFrame(rows, columns=["janela", "métrica", "valor"])


def build_figure(
    df: pd.DataFrame, time_col: str, time_scale: float, pairs: list[red.ChannelPair]
) -> go.Figure:
    if len(df) > MAX_PLOT_POINTS:
        step = max(1, len(df) // MAX_PLOT_POINTS)
        df = df.iloc[::step]
    time = df[time_col] * time_scale
    fig = make_subplots(
        rows=len(pairs), cols=1, shared_xaxes=True,
        subplot_titles=[p.suffix for p in pairs],
    )
    for i, pair in enumerate(pairs, start=1):
        # ref larga + semi-transparente por baixo, vhdl fina + opaca por
        # cima ("halo"): ver comentário em SERIES_STYLE -- dash em cima de
        # traço largo do mesmo tom vira mistura arroxeada ilegível quando as
        # duas quase coincidem (o caso bom); sólido+opacidade não tem esse
        # problema em nenhum zoom.
        fig.add_trace(
            go.Scattergl(x=time, y=df[pair.ref_col], name=f"ref ({pair.suffix})",
                         line=dict(color=_rgba(COLOR_BLUE, 0.55), width=4)),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scattergl(x=time, y=df[pair.vhdl_col], name=f"vhdl ({pair.suffix})",
                         line=dict(color=COLOR_RED, width=1.6)),
            row=i, col=1,
        )
    fig.update_layout(height=280 * len(pairs), showlegend=True, template="plotly_white")
    fig.update_xaxes(title_text="Tempo (s)", row=len(pairs), col=1)
    return fig


def has_data(run_dir: Path) -> bool:
    """True se o run tem série temporal visível (CSV ou .npz)."""
    return red.find_timeseries_csv(run_dir) is not None or bool(red.list_npz_windows(run_dir))


def render_run(run_dir: Path, case_dir: Path) -> None:
    """Renderiza o conteúdo de um run já resolvido: gráfico(s) + métricas.

    Bloco idêntico entre results_explorer_app.py e
    results_presentation_app.py — a única diferença entre os dois apps é
    como cada um chega até `run_dir` (navegação por campanha vs. por
    nível canônico); a partir daqui o comportamento é o mesmo.
    """
    csv_path = red.find_timeseries_csv(run_dir)
    npz_windows = {} if csv_path is not None else red.list_npz_windows(run_dir)

    if csv_path is not None:
        pairs = red.detect_channel_pairs(csv_path)
        if not pairs:
            st.warning("Sem canais vhdl_*/ref_* reconhecidos neste CSV.")
        else:
            labels = [p.suffix for p in pairs]
            selected = st.multiselect("Canais", labels, default=labels)
            selected_pairs = [p for p in pairs if p.suffix in selected]
            if selected_pairs:
                time_col, time_scale = red.detect_time_column(csv_path)
                columns = [time_col] + [
                    c for p in selected_pairs for c in (p.vhdl_col, p.ref_col)
                ]
                df = load_csv(str(csv_path), csv_path.stat().st_mtime, columns)
                fig = build_figure(df, time_col, time_scale, selected_pairs)
                st.plotly_chart(fig, width="stretch", theme=None)
    elif npz_windows:
        # L4 (FPGA real) run: capture split em janelas partida/regime, cada
        # uma com seu proprio .npz (fpga_*/cmod_* em vez de vhdl_*/ref_*).
        # Alem das janelas (FPGA vs C), oferece a captura completa (so FPGA),
        # o ensaio inteiro lido do .hilbin bruto.
        FULL = "📈 Ensaio completo (só FPGA)"
        _WIN_LABEL = {
            "partida": "🔍 Zoom — partida (transitório inicial)",
            "regime": "🔍 Zoom — regime (estado estacionário)",
        }
        hilbin = find_raw_hilbin(case_dir)
        label_to_win = {_WIN_LABEL.get(w, w): w for w in npz_windows}
        options = ([FULL] if hilbin is not None else []) + list(label_to_win)
        st.sidebar.caption(
            "O 'Ensaio completo' mostra toda a captura (só a placa, correntes de fase a/b/c). "
            "Os 'Zoom' comparam FPGA × modelo C (× PSIM, quando disponível) numa janela — "
            "mas em α/β (Clarke), não fase a/b/c: por isso não existe canal 'ic' ali, "
            "iα/iβ juntas já descrevem o sistema trifásico equilibrado."
        )
        # key=case_dir por segurança/consistência com os outros seletores
        # (Ensaio/Sub-resultado) -- aqui as opções são strings estáveis
        # entre casos, mas evita depender disso continuar sendo verdade.
        choice = st.sidebar.selectbox("Vista", options, index=0, key=f"vista_{case_dir}")
        if choice == FULL:
            data = load_full_capture(str(hilbin), hilbin.stat().st_mtime)
            st.caption(
                f"Captura completa do ensaio (FPGA real) — {data['n_full']:,} amostras "
                f"decimadas para visualização. Correntes reconstruídas em três fases."
            )
            st.plotly_chart(build_full_capture_figure(data), width="stretch", theme=None)
        else:
            window = label_to_win[choice]
            npz_path = npz_windows[window]
            data = load_npz(str(npz_path), npz_path.stat().st_mtime)
            pairs = red.detect_npz_channel_pairs(list(data.keys()))
            if not pairs:
                st.warning("Sem canais fpga_*/cmod_* reconhecidos neste .npz.")
            else:
                has_psim = any(p.psim_key is not None for p in pairs)
                # Legenda curta sempre visível; o parágrafo técnico completo
                # (inversão de polaridade do PSIM, eixos de Clarke) fica num
                # expander fechado por padrão -- não deve competir com o
                # gráfico pela atenção de quem só quer ver a curva.
                short = "🔴 FPGA (real) · 🔵 C (referência)"
                if has_psim:
                    short += " · 🟢 PSIM (motor nativo)"
                st.caption(short)
                with st.expander("ℹ️ Detalhes sobre as séries e os eixos"):
                    details = (
                        "**FPGA (real)** — telemetria da placa.\n\n"
                        "**C (referência)** — mesmo modelo C/C++ usado em L2/L3, aqui "
                        "alimentado pelo PWM capturado da FPGA (`l4_pwm_replay`)."
                    )
                    if has_psim:
                        details += (
                            "\n\n**PSIM (motor nativo)** — simulação independente no PSIM "
                            "(V/f + portadora + NPC + bloco de motor de indução nativo do "
                            "PSIM, `Iu/Iv/Iw/motorSpeed`) — não é o modelo C/DLL (`IuSim1` "
                            "etc.), que existe no mesmo schematic mas não é usado aqui. "
                            "⚠️ `ia`/`ib` do PSIM têm o sinal invertido artificialmente na "
                            "conversão (`psim_csv_to_npz.py`) — correção de polaridade do "
                            "probe de corrente do PSIM, confirmada por correlação cruzada "
                            "em S0/A1 (r≈0,94-0,96 após inverter, vs. r≈0,6-0,8 sem "
                            "inverter; descartada troca de eixo α/β e defasagem temporal)."
                        )
                    details += (
                        "\n\nEixos `iα`/`iβ`/`ψα`/`ψβ` são o referencial estacionário de "
                        "Clarke, não fase a/b/c — não existe canal `ic` por isso."
                    )
                    st.markdown(details)
                labels = [p.suffix for p in pairs]
                selected = st.multiselect(
                    "Canais", labels, default=labels,
                    format_func=lambda s: SUFFIX_LABELS.get(s, s),
                )
                selected_pairs = [p for p in pairs if p.suffix in selected]
                if selected_pairs:
                    fig = build_npz_figure(data, selected_pairs)
                    st.plotly_chart(fig, width="stretch", theme=None)
    else:
        st.info("Sem série temporal reconhecida para este run.")

    metrics = red.load_metrics(run_dir)
    if metrics:
        st.subheader("Métricas")
        st.table(flatten_metrics(metrics))
    else:
        st.caption("Sem metrics.json para este run.")
