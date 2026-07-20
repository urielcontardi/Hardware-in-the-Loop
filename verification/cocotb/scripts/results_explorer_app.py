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

    campaign_dir = st.sidebar.selectbox(
        "Campanha", campaigns, index=len(campaigns) - 1, format_func=lambda p: p.name
    )

    cases = red.list_cases(campaign_dir)
    if not cases:
        st.info("Nenhum caso encontrado nesta campanha.")
        return
    case_dir = st.sidebar.selectbox("Caso", cases, format_func=lambda p: p.name)

    runs = red.list_runs(case_dir)
    if not runs:
        st.info("Nenhum run encontrado neste caso.")
        return
    run_dir = st.sidebar.selectbox("Run", runs, format_func=lambda p: p.name)

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
        window = st.sidebar.selectbox("Janela", list(npz_windows), index=len(npz_windows) - 1)
        npz_path = npz_windows[window]
        data = _load_npz(str(npz_path), npz_path.stat().st_mtime)
        pairs = red.detect_npz_channel_pairs(list(data.keys()))
        if not pairs:
            st.warning("Sem canais fpga_*/cmod_* reconhecidos neste .npz.")
        else:
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
