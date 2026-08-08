#!/usr/bin/env python3
"""Explorador interativo de resultados HIL (campanhas em verification/results/).

Uso:
    cd verification/cocotb
    uv run streamlit run scripts/results_explorer_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import results_explorer_data as red
import results_explorer_render as render

st.set_page_config(page_title="HIL Results Explorer", layout="wide")


_CAMPAIGN_INFO: dict[str, str] = {
    "2026-07-25_campaign_l4_final": "L4 (hardware) — campanha final, capturas com regime estacionário pleno ✅",
    "2026-07-25_campaign_l4_v2": "L4 (hardware) — aquisição intermediária (processamento incompleto; prefira a _final)",
    "2026-07-23_campaign_l4_q438": "L4 (hardware) — solver corrigido, mas janela de regime no fim da rampa",
    "2026-07-14_campaign_l4": "L4 (hardware) — campanha antiga (solver com erro de L_m)",
    "2026-07-04_campaign_03": "L2/L3 (simulação) — solver isolado e cadeia integrada",
    "2026-07-23_campaign_q438": "L2/L3 (simulação) — reexecução (índice; dados em campaign_03)",
}


def _campaign_label(p: Path) -> str:
    extra = _CAMPAIGN_INFO.get(p.name)
    return f"{p.name}  ·  {extra}" if extra else p.name


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
        render.GROUP_ORDER.index(render.CASE_INFO[render.case_id(c)]["grupo"])
        if render.case_id(c) in render.CASE_INFO else 99,
        c.name,
    ))
    # key=campanha: sem isso o Streamlit reaproveita a seleção anterior do
    # widget ao trocar de campanha -- o Path "herdado" pode apontar pro
    # caso errado. Ver mesmo comentário em results_presentation_app.py.
    case_dir = st.sidebar.selectbox(
        "2️⃣ Ensaio", cases, format_func=render.case_label, key=f"ensaio_{campaign_dir}"
    )

    # Explica o caso selecionado, para não depender de decorar S0/A5/B2.
    _info = render.CASE_INFO.get(render.case_id(case_dir))
    if _info:
        st.subheader(_info["nome"])
        st.info(f"**{_info['grupo']}.** {_info['desc']}")

    runs = red.list_runs(case_dir)
    # Mantém só os sub-resultados que têm série temporal visível (CSV ou .npz),
    # escondendo pastas auxiliares como 'raw'. Se sobrar um só, nem mostra o seletor.
    runs_viz = [r for r in runs if render.has_data(r)] or runs
    if not runs_viz:
        st.info("Nenhum dado visualizável neste caso.")
        return
    if len(runs_viz) == 1:
        run_dir = runs_viz[0]
    else:
        run_dir = st.sidebar.selectbox(
            "3️⃣ Sub-resultado", runs_viz, format_func=lambda p: p.name,
            key=f"subresultado_{case_dir}",
        )

    render.render_run(run_dir, case_dir)


if __name__ == "__main__":
    main()
