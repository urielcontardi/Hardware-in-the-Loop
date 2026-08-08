#!/usr/bin/env python3
"""Versão curada do explorador de resultados HIL, para apresentação (não
uso exploratório pessoal — ver results_explorer_app.py para isso).

Navegação fixa Nível de validação (L2/L3/L4) → Caso, sem seletor de
campanha: cada nível aponta para sua campanha canônica, hardcoded abaixo.
Publicada em https://hil.contardi.dev/results (ver docker-compose.results.yml
e docs/superpowers/specs/2026-08-03-results-presentation-app-design.md).

Uso local:
    cd verification/cocotb
    uv run streamlit run scripts/results_presentation_app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import results_explorer_data as red
import results_explorer_render as render

st.set_page_config(page_title="HIL — Resultados de Validação", layout="wide")

# Campanha canônica por nível — únicas fontes de dado desta vista curada.
# Se uma nova campanha se tornar canônica, atualizar aqui.
_L2L3_CAMPAIGN = "2026-07-04_campaign_03"
_L4_CAMPAIGN = "2026-07-25_campaign_l4_final"

_LEVELS = ["L2", "L3", "L4"]


@st.cache_data
def _load_story() -> dict:
    path = red.RESULTS_ROOT / _L2L3_CAMPAIGN / "campaign_story.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _level_meta(level: str) -> dict:
    story = _load_story()
    for lvl in story["levels"]:
        if lvl["id"] == level:
            return lvl
    return {"title": level, "question": "", "note": ""}


def _campaign_for(level: str) -> Path:
    name = _L2L3_CAMPAIGN if level in ("L2", "L3") else _L4_CAMPAIGN
    return red.RESULTS_ROOT / name


@st.cache_data
def _common_case_ids() -> set[str]:
    """Casos com captura em hardware (L4) -- o subconjunto comum aos 3
    níveis. L2/L3 têm a matriz completa (S0+A1-A7+B1-B3) mas L4 só tem os
    6 ensaios efetivamente capturados na placa; sem esse filtro, trocar de
    nível faz o "Ensaio" selecionado sumir da lista pra quem não tem L4."""
    l4_dir = red.RESULTS_ROOT / _L4_CAMPAIGN
    return {render.case_id(c) for c in red.list_cases(l4_dir)}


def main() -> None:
    st.title("Validação HIL — do solver isolado à placa real")
    st.caption(
        "Três níveis de validação, do modelo mais isolado (solver VHDL sozinho) "
        "ao mais completo (placa FPGA real). Escolha um nível e um ensaio da matriz."
    )

    level = st.sidebar.radio(
        "1️⃣ Nível de validação", _LEVELS,
        format_func=lambda lv: f"{lv} — {_level_meta(lv)['title']}",
    )
    meta = _level_meta(level)
    st.subheader(f"{level} — {meta['title']}")
    if meta.get("question"):
        st.info(f"**Pergunta que este nível responde:** {meta['question']}")
    if meta.get("note"):
        st.caption(meta["note"])

    campaign_dir = _campaign_for(level)
    if not campaign_dir.is_dir():
        st.error(f"Campanha canônica ausente em disco: {campaign_dir}")
        return

    common_ids = _common_case_ids()
    cases = [c for c in red.list_cases(campaign_dir) if render.case_id(c) in common_ids]
    if not cases:
        st.info("Nenhum caso encontrado nesta campanha.")
        return
    cases = sorted(cases, key=lambda c: (
        render.GROUP_ORDER.index(render.CASE_INFO[render.case_id(c)]["grupo"])
        if render.case_id(c) in render.CASE_INFO else 99,
        c.name,
    ))
    # key=level: sem isso o Streamlit reaproveita a seleção anterior do
    # widget (mesmo rótulo "2️⃣ Ensaio") ao trocar de nível -- L4 usa uma
    # campanha diferente de L2/L3, então o Path "herdado" aponta pro caso
    # errado (mesmo label exibido) e o run fica vazio. key por nível força
    # o Streamlit a tratar cada nível como um widget próprio.
    case_dir = st.sidebar.selectbox(
        "2️⃣ Ensaio", cases, format_func=render.case_label, key=f"ensaio_{level}"
    )
    st.sidebar.caption(
        "Mostrando só os ensaios com captura nos 3 níveis (S0, A1, A3, A5, B1, B2) — "
        "os demais casos da matriz (A2, A4, A6, A7, B3) não têm validação em hardware (L4)."
    )

    info = render.CASE_INFO.get(render.case_id(case_dir))
    if info:
        st.markdown(f"**{info['nome']}**")
        st.info(f"**{info['grupo']}.** {info['desc']}")

    prefix = f"{level.lower()}_"
    runs = [r for r in red.list_runs(case_dir) if r.name.startswith(prefix)]
    runs_viz = [r for r in runs if render.has_data(r)]
    if not runs_viz:
        st.info(f"Nenhum resultado de {level} disponível para este ensaio.")
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
