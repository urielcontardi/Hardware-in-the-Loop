#!/usr/bin/env python3
"""Explorador interativo de resultados HIL (campanhas em verification/results/).

Uso:
    cd verification/cocotb
    uv run streamlit run scripts/results_explorer_app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent))
import results_explorer_data as red

st.set_page_config(page_title="HIL Results Explorer", layout="wide")


@st.cache_data
def _load_csv(csv_path: str, mtime: float, columns: list[str]) -> pd.DataFrame:
    return pd.read_csv(csv_path, usecols=columns)


@st.cache_data
def _load_npz(npz_path: str, mtime: float) -> dict:
    return red.load_npz_window(Path(npz_path))


def _find_raw_hilbin(case_dir: Path) -> Path | None:
    """Localiza a captura .hilbin bruta de um caso L4 (varre subpastas)."""
    for cand in sorted(case_dir.rglob("*.hilbin")):
        return cand
    return None


@st.cache_data
def _load_full_capture(hilbin_path: str, mtime: float, max_pts: int = 6000) -> dict:
    """Trajetória FPGA completa (todo o ensaio) direto do .hilbin, decimada.

    As correntes vêm do hardware em α/β (campos ia/ib); reconstrói as três
    fases por Clarke inversa, igual ao gerador da figura de visão geral.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def _build_full_capture_figure(d: dict) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        subplot_titles=["Correntes de fase [A]", "|ψ_r| [Wb]", "ω [rad/s]"],
    )
    for y, name, color in ((d["ia"], "i_a", "#1f77b4"), (d["ib"], "i_b", "#ff7f0e"),
                           (d["ic"], "i_c", "#2ca02c")):
        fig.add_trace(go.Scattergl(x=d["t"], y=y, name=name, line=dict(color=color, width=1)),
                      row=1, col=1)
    fig.add_trace(go.Scattergl(x=d["t"], y=d["flux"], name="|ψ_r|", line=dict(color="#1f77b4")),
                  row=2, col=1)
    fig.add_trace(go.Scattergl(x=d["t"], y=d["speed"], name="ω", line=dict(color="#d62728")),
                  row=3, col=1)
    fig.update_xaxes(title_text="Tempo (s)", row=3, col=1)
    fig.update_layout(height=760, showlegend=True, template="plotly_white", hovermode="x unified")
    return fig


def _build_npz_figure(data: dict, pairs: list[red.NpzChannelPair]) -> go.Figure:
    fig = make_subplots(
        rows=len(pairs), cols=1, shared_xaxes=True,
        subplot_titles=[p.suffix for p in pairs],
    )
    for i, pair in enumerate(pairs, start=1):
        fig.add_trace(
            go.Scattergl(x=data["cmod_t"], y=data[pair.cmod_key], name=f"C (referência) — {pair.suffix}",
                         line=dict(color="#1f77b4")),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scattergl(x=data["fpga_t"], y=data[pair.fpga_key], name=f"FPGA (real) — {pair.suffix}",
                         line=dict(color="#d62728")),
            row=i, col=1,
        )
    fig.update_layout(height=280 * len(pairs), showlegend=True, template="plotly_white")
    fig.update_xaxes(title_text="Tempo (s)", row=len(pairs), col=1)
    return fig


_KNOWN_WINDOW_LABELS = ("partida", "regime")

# ── Navegação amigável ──────────────────────────────────────────────────────
# Cada caso da matriz tem um identificador curto (S0, A1..A7, B1..B3). Aqui eles
# ganham nome legível, grupo e uma descrição do que o ensaio testa.
_CASE_INFO: dict[str, dict[str, str]] = {
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
_GROUP_ORDER = ["Sanidade", "Partida e aceleração", "Perturbação de carga"]

_CAMPAIGN_INFO: dict[str, str] = {
    "2026-07-25_campaign_l4_final": "L4 (hardware) — campanha final, capturas com regime estacionário pleno ✅",
    "2026-07-25_campaign_l4_v2": "L4 (hardware) — aquisição intermediária (processamento incompleto; prefira a _final)",
    "2026-07-23_campaign_l4_q438": "L4 (hardware) — solver corrigido, mas janela de regime no fim da rampa",
    "2026-07-14_campaign_l4": "L4 (hardware) — campanha antiga (solver com erro de L_m)",
    "2026-07-04_campaign_03": "L2/L3 (simulação) — solver isolado e cadeia integrada",
    "2026-07-23_campaign_q438": "L2/L3 (simulação) — reexecução (índice; dados em campaign_03)",
}


def _case_id(case_dir: Path) -> str:
    """Extrai o identificador curto (S0, A5, B2...) do nome da pasta do caso."""
    return case_dir.name.split("_")[0].upper()


def _case_label(case_dir: Path) -> str:
    info = _CASE_INFO.get(_case_id(case_dir))
    return info["nome"] if info else case_dir.name


def _campaign_label(p: Path) -> str:
    extra = _CAMPAIGN_INFO.get(p.name)
    return f"{p.name}  ·  {extra}" if extra else p.name


def _flatten_metrics(metrics: dict) -> pd.DataFrame:
    """L4 metrics.json nests per-window blocks (partida/regime, each a dict of
    scalar metrics) alongside run-level scalars/dicts (params, vdc, ...).
    Flatten only the known window blocks into (janela, métrica, valor) rows;
    everything else falls back to the flat métrica/valor view."""
    windows = {k: metrics[k] for k in _KNOWN_WINDOW_LABELS if isinstance(metrics.get(k), dict)}
    if not windows:
        return pd.DataFrame(metrics.items(), columns=["métrica", "valor"])
    rows = []
    for window, block in windows.items():
        for key, value in block.items():
            if isinstance(value, dict):
                value = json.dumps(value)
            rows.append((window, key, value))
    return pd.DataFrame(rows, columns=["janela", "métrica", "valor"])


def _build_figure(
    df: pd.DataFrame, time_col: str, time_scale: float, pairs: list[red.ChannelPair]
) -> go.Figure:
    time = df[time_col] * time_scale
    fig = make_subplots(
        rows=len(pairs), cols=1, shared_xaxes=True,
        subplot_titles=[p.suffix for p in pairs],
    )
    for i, pair in enumerate(pairs, start=1):
        fig.add_trace(
            go.Scattergl(x=time, y=df[pair.ref_col], name=f"ref ({pair.suffix})",
                         line=dict(color="#1f77b4")),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scattergl(x=time, y=df[pair.vhdl_col], name=f"vhdl ({pair.suffix})",
                         line=dict(color="#d62728")),
            row=i, col=1,
        )
    fig.update_layout(height=280 * len(pairs), showlegend=True, template="plotly_white")
    fig.update_xaxes(title_text="Tempo (s)", row=len(pairs), col=1)
    return fig


def main() -> None:
    st.title("HIL Results Explorer")

    campaigns = red.list_campaigns()
    if not campaigns:
        st.error(f"Nenhuma campanha encontrada em {red.RESULTS_ROOT}")
        return

    # Campanha: preferir a campanha final (L4 com regime pleno) como padrão.
    default_idx = next((i for i, p in enumerate(campaigns)
                        if p.name == "2026-07-25_campaign_l4_final"), len(campaigns) - 1)
    campaign_dir = st.sidebar.selectbox(
        "1️⃣ Campanha", campaigns, index=default_idx, format_func=_campaign_label
    )
    if campaign_dir.name in _CAMPAIGN_INFO:
        st.sidebar.caption(_CAMPAIGN_INFO[campaign_dir.name])

    cases = red.list_cases(campaign_dir)
    if not cases:
        st.info("Nenhum caso encontrado nesta campanha.")
        return
    # Ordena os casos por grupo (Sanidade → Partida → Degrau) e depois por id.
    cases = sorted(cases, key=lambda c: (
        _GROUP_ORDER.index(_CASE_INFO[_case_id(c)]["grupo"]) if _case_id(c) in _CASE_INFO else 99,
        c.name,
    ))
    case_dir = st.sidebar.selectbox("2️⃣ Ensaio", cases, format_func=_case_label)

    # Explica o caso selecionado, para não depender de decorar S0/A5/B2.
    _info = _CASE_INFO.get(_case_id(case_dir))
    if _info:
        st.subheader(_info["nome"])
        st.info(f"**{_info['grupo']}.** {_info['desc']}")

    runs = red.list_runs(case_dir)
    # Mantém só os sub-resultados que têm série temporal visível (CSV ou .npz),
    # escondendo pastas auxiliares como 'raw'. Se sobrar um só, nem mostra o seletor.
    def _has_data(r: Path) -> bool:
        return red.find_timeseries_csv(r) is not None or bool(red.list_npz_windows(r))
    runs_viz = [r for r in runs if _has_data(r)] or runs
    if not runs_viz:
        st.info("Nenhum dado visualizável neste caso.")
        return
    if len(runs_viz) == 1:
        run_dir = runs_viz[0]
    else:
        run_dir = st.sidebar.selectbox("3️⃣ Sub-resultado", runs_viz, format_func=lambda p: p.name)

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
                df = _load_csv(str(csv_path), csv_path.stat().st_mtime, columns)
                fig = _build_figure(df, time_col, time_scale, selected_pairs)
                st.plotly_chart(fig, width="stretch")
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
        hilbin = _find_raw_hilbin(case_dir)
        label_to_win = {_WIN_LABEL.get(w, w): w for w in npz_windows}
        options = ([FULL] if hilbin is not None else []) + list(label_to_win)
        st.sidebar.caption("O 'Ensaio completo' mostra toda a captura (só a placa). "
                           "Os 'Zoom' comparam FPGA × modelo C numa janela.")
        choice = st.sidebar.selectbox("3️⃣ Vista", options, index=0)
        if choice == FULL:
            data = _load_full_capture(str(hilbin), hilbin.stat().st_mtime)
            st.caption(
                f"Captura completa do ensaio (FPGA real) — {data['n_full']:,} amostras "
                f"decimadas para visualização. Correntes reconstruídas em três fases."
            )
            st.plotly_chart(_build_full_capture_figure(data), width="stretch")
        else:
            window = label_to_win[choice]
            npz_path = npz_windows[window]
            data = _load_npz(str(npz_path), npz_path.stat().st_mtime)
            pairs = red.detect_npz_channel_pairs(list(data.keys()))
            if not pairs:
                st.warning("Sem canais fpga_*/cmod_* reconhecidos neste .npz.")
            else:
                st.caption("Comparação FPGA real (vermelho) × modelo C de referência (azul) na janela.")
                labels = [p.suffix for p in pairs]
                selected = st.multiselect("Canais", labels, default=labels)
                selected_pairs = [p for p in pairs if p.suffix in selected]
                if selected_pairs:
                    fig = _build_npz_figure(data, selected_pairs)
                    st.plotly_chart(fig, width="stretch")
    else:
        st.info("Sem série temporal reconhecida para este run.")

    metrics = red.load_metrics(run_dir)
    if metrics:
        st.subheader("Métricas")
        if npz_windows:
            st.table(_flatten_metrics(metrics))
        else:
            st.table(pd.DataFrame(metrics.items(), columns=["métrica", "valor"]))
    else:
        st.caption("Sem metrics.json para este run.")


if __name__ == "__main__":
    main()
