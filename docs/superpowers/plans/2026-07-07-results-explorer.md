# Explorador Interativo de Resultados HIL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit app that lets the user browse `verification/results/*_campaign_*/` (campaign → case → run), plot VHDL-vs-reference time series with interactive zoom, and see the run's `metrics.json` — to help pick material for the dissertation results chapter.

**Architecture:** A pure, dependency-light data-loading module (`results_explorer_data.py`, stdlib only — `pathlib`/`csv`/`json`) resolves what exists on disk (never trusting `manifest.json`) and detects plottable channel pairs from a CSV header. A thin Streamlit UI module (`results_explorer_app.py`) consumes it, reading full CSV data via `pandas` and plotting via `plotly` (already a project dependency).

**Tech Stack:** Python 3.12, `streamlit` (new), `pandas` (new), `plotly` (existing), stdlib `csv`/`json`/`pathlib`, `pytest` (existing).

## Global Constraints

- Data source is exactly `verification/results/*_campaign_*/` — never `verification/cocotb/reports/hilbin*` and never anything from the `Mestrado_latex` repo (out of scope per spec).
- File existence on disk is the only source of truth: a campaign's cases are its subdirectories, a case's runs are its subdirectories — never read `manifest.json` to build these lists (confirmed stale in the related `chapter_common.py` spec/plan).
- `results_explorer_data.py` must not import `streamlit` — it must be testable standalone with `pytest`.
- CSV candidate priority order for `find_timeseries_csv`, exactly: `vf_vhdl_vs_c.csv`, `top_pwm_replay_vs_c.csv`, `sine_vhdl_vs_c.csv`, `ref_vhdl_vs_c.csv`, `fullstack_vs_top.csv`.
- Nothing may raise an unhandled exception up to the Streamlit UI — missing campaigns/cases/runs/CSV/metrics all degrade to an on-page message, never a crash.
- No cross-case comparison view, no auth, no remote deploy — local single-user tool only.
- New dependencies (`streamlit`, `pandas`) added to `verification/cocotb/pyproject.toml` via `uv add`.
- Run command: `cd verification/cocotb && uv run streamlit run scripts/results_explorer_app.py`.
- No automated test for `results_explorer_app.py` itself (UI) — verified manually only, per spec.

---

### Task 1: `results_explorer_data.py` — pure data-loading module

**Files:**
- Create: `verification/cocotb/scripts/results_explorer_data.py`
- Test: `verification/cocotb/scripts/tests/test_results_explorer_data.py`

**Interfaces:**
- Produces (used by Task 2):
  - `REPO_ROOT: Path`, `RESULTS_ROOT: Path`, `TIMESERIES_CSV_CANDIDATES: list[str]`
  - `@dataclass ChannelPair(suffix: str, vhdl_col: str, ref_col: str)`
  - `list_campaigns(results_root: Path = RESULTS_ROOT) -> list[Path]`
  - `list_cases(campaign_dir: Path) -> list[Path]`
  - `list_runs(case_dir: Path) -> list[Path]`
  - `find_timeseries_csv(run_dir: Path) -> Path | None`
  - `detect_channel_pairs(csv_path: Path) -> list[ChannelPair]`
  - `detect_time_column(csv_path: Path) -> tuple[str, float]`
  - `load_metrics(run_dir: Path) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `verification/cocotb/scripts/tests/test_results_explorer_data.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import results_explorer_data as red


def test_list_campaigns_returns_sorted_campaign_dirs(tmp_path):
    (tmp_path / "2026-06-29_campaign_01").mkdir()
    (tmp_path / "2026-07-04_campaign_03").mkdir()
    (tmp_path / "not_a_campaign").mkdir()
    (tmp_path / "some_file.txt").write_text("x")

    campaigns = red.list_campaigns(tmp_path)

    assert [c.name for c in campaigns] == ["2026-06-29_campaign_01", "2026-07-04_campaign_03"]


def test_list_campaigns_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist"

    assert red.list_campaigns(missing) == []


def test_list_cases_excludes_dashboard_and_hidden(tmp_path):
    (tmp_path / "A1_tacc0p5s_load000").mkdir()
    (tmp_path / "campaign_dashboard").mkdir()
    (tmp_path / ".hidden").mkdir()

    cases = red.list_cases(tmp_path)

    assert [c.name for c in cases] == ["A1_tacc0p5s_load000"]


def test_list_runs_returns_sorted_subdirs(tmp_path):
    (tmp_path / "l3_top_pwm_replay_vf_2s").mkdir()
    (tmp_path / "l2_vf_2s_realts").mkdir()

    runs = red.list_runs(tmp_path)

    assert [r.name for r in runs] == ["l2_vf_2s_realts", "l3_top_pwm_replay_vf_2s"]


def test_find_timeseries_csv_picks_first_candidate_in_priority_order(tmp_path):
    (tmp_path / "sine_vhdl_vs_c.csv").write_text("t_us\n0\n")
    (tmp_path / "vf_vhdl_vs_c.csv").write_text("t_us\n0\n")

    found = red.find_timeseries_csv(tmp_path)

    assert found.name == "vf_vhdl_vs_c.csv"


def test_find_timeseries_csv_returns_none_when_no_candidate(tmp_path):
    (tmp_path / "metrics.json").write_text("{}")

    assert red.find_timeseries_csv(tmp_path) is None


def test_detect_channel_pairs_matches_ref_prefix_and_ignores_unpaired(tmp_path):
    csv_path = tmp_path / "vf_vhdl_vs_c.csv"
    csv_path.write_text("t_us,vhdl_i_alpha,ref_i_alpha,vhdl_lonely\n0,0.1,0.1,9\n")

    pairs = red.detect_channel_pairs(csv_path)

    assert len(pairs) == 1
    assert pairs[0].suffix == "i_alpha"
    assert pairs[0].vhdl_col == "vhdl_i_alpha"
    assert pairs[0].ref_col == "ref_i_alpha"


def test_detect_channel_pairs_falls_back_to_c_prefix(tmp_path):
    csv_path = tmp_path / "fullstack_vs_top.csv"
    csv_path.write_text("t_s,vhdl_speed,c_speed\n0,0.0,0.0\n")

    pairs = red.detect_channel_pairs(csv_path)

    assert pairs == [red.ChannelPair(suffix="speed", vhdl_col="vhdl_speed", ref_col="c_speed")]


def test_detect_time_column_prefers_t_s(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("t_s,vhdl_speed\n0,0\n")

    assert red.detect_time_column(csv_path) == ("t_s", 1.0)


def test_detect_time_column_falls_back_to_t_us_scaled(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("t_us,vhdl_speed\n0,0\n")

    assert red.detect_time_column(csv_path) == ("t_us", 1e-6)


def test_load_metrics_returns_metrics_subkey(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": {"nrmse_i_alpha": 0.03}}))

    assert red.load_metrics(tmp_path) == {"nrmse_i_alpha": 0.03}


def test_load_metrics_missing_file_returns_none(tmp_path):
    assert red.load_metrics(tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_results_explorer_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'results_explorer_data'`.

- [ ] **Step 3: Implement `results_explorer_data.py`**

Create `verification/cocotb/scripts/results_explorer_data.py`:

```python
#!/usr/bin/env python3
"""Data loading for the interactive HIL results explorer (Streamlit app).

Reads verification/results/*_campaign_*/ straight from disk. Never trusts
manifest.json -- a campaign's cases are its subdirectories, a case's runs
are its subdirectories (see docs/superpowers/specs/
2026-07-07-results-explorer-design.md and the related chapter_common.py
spec for why manifest.json is not a reliable source: l2_results/
l3_results have been observed empty even when metrics.json exists on
disk). No streamlit import here -- this module is plain stdlib so it can
be unit tested standalone.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "verification" / "results"

TIMESERIES_CSV_CANDIDATES = [
    "vf_vhdl_vs_c.csv",
    "top_pwm_replay_vs_c.csv",
    "sine_vhdl_vs_c.csv",
    "ref_vhdl_vs_c.csv",
    "fullstack_vs_top.csv",
]


@dataclass
class ChannelPair:
    suffix: str
    vhdl_col: str
    ref_col: str


def list_campaigns(results_root: Path = RESULTS_ROOT) -> list[Path]:
    if not results_root.is_dir():
        return []
    return sorted(p for p in results_root.iterdir() if p.is_dir() and "campaign" in p.name)


def list_cases(campaign_dir: Path) -> list[Path]:
    if not campaign_dir.is_dir():
        return []
    return sorted(
        p for p in campaign_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != "campaign_dashboard"
    )


def list_runs(case_dir: Path) -> list[Path]:
    if not case_dir.is_dir():
        return []
    return sorted(p for p in case_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def find_timeseries_csv(run_dir: Path) -> Path | None:
    for name in TIMESERIES_CSV_CANDIDATES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_header(csv_path: Path) -> list[str]:
    with csv_path.open(newline="") as f:
        return next(csv.reader(f))


def detect_channel_pairs(csv_path: Path) -> list[ChannelPair]:
    header = _read_header(csv_path)
    columns = set(header)
    pairs = []
    for col in header:
        if not col.startswith("vhdl_"):
            continue
        suffix = col[len("vhdl_"):]
        ref_col = f"ref_{suffix}"
        if ref_col not in columns:
            ref_col = f"c_{suffix}"
        if ref_col in columns:
            pairs.append(ChannelPair(suffix=suffix, vhdl_col=col, ref_col=ref_col))
    return pairs


def detect_time_column(csv_path: Path) -> tuple[str, float]:
    header = _read_header(csv_path)
    if "t_s" in header:
        return "t_s", 1.0
    return "t_us", 1e-6


def load_metrics(run_dir: Path) -> dict | None:
    path = run_dir / "metrics.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return doc.get("metrics", doc)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd verification/cocotb
uv run pytest scripts/tests/test_results_explorer_data.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/results_explorer_data.py \
        verification/cocotb/scripts/tests/test_results_explorer_data.py
git commit -m "$(cat <<'EOF'
feat(validation): results_explorer_data — loader p/ explorador interativo

Modulo stdlib puro (sem streamlit) que resolve campanhas/casos/runs
por disco (nao manifest.json), acha o CSV de serie temporal e detecta
pares de canal vhdl_*/ref_* (ou c_* p/ fullstack_vs_top.csv).
EOF
)"
```

---

### Task 2: `results_explorer_app.py` — Streamlit UI

**Files:**
- Modify: `verification/cocotb/pyproject.toml` (add `streamlit`, `pandas`)
- Create: `verification/cocotb/scripts/results_explorer_app.py`

**Interfaces:**
- Consumes: `results_explorer_data.REPO_ROOT`, `.RESULTS_ROOT`, `.ChannelPair`, `.list_campaigns`, `.list_cases`, `.list_runs`, `.find_timeseries_csv`, `.detect_channel_pairs`, `.detect_time_column`, `.load_metrics` (Task 1).
- Produces: none consumed by other tasks — this is the terminal UI script.

- [ ] **Step 1: Add the new dependencies**

```bash
cd verification/cocotb
uv add streamlit pandas
uv run python3 -c "import streamlit, pandas; print(streamlit.__version__, pandas.__version__)"
```

Expected: prints two version strings (e.g. `1.x.x 2.x.x`), and `verification/cocotb/pyproject.toml` now lists `streamlit` and `pandas` under `dependencies`.

- [ ] **Step 2: Implement `results_explorer_app.py`**

Create `verification/cocotb/scripts/results_explorer_app.py`:

```python
#!/usr/bin/env python3
"""Explorador interativo de resultados HIL (campanhas em verification/results/).

Uso:
    cd verification/cocotb
    uv run streamlit run scripts/results_explorer_app.py
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

st.set_page_config(page_title="HIL Results Explorer", layout="wide")


@st.cache_data
def _load_csv(csv_path: str, mtime: float, columns: list[str]) -> pd.DataFrame:
    return pd.read_csv(csv_path, usecols=columns)


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
                         line=dict(color="gray", dash="dash")),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scattergl(x=time, y=df[pair.vhdl_col], name=f"vhdl ({pair.suffix})",
                         line=dict(color="black")),
            row=i, col=1,
        )
    fig.update_layout(height=280 * len(pairs), showlegend=True)
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
    if csv_path is None:
        st.info("Sem série temporal reconhecida para este run.")
    else:
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
                st.plotly_chart(fig, use_container_width=True)

    metrics = red.load_metrics(run_dir)
    if metrics:
        st.subheader("Métricas")
        st.table(pd.DataFrame(metrics.items(), columns=["métrica", "valor"]))
    else:
        st.caption("Sem metrics.json para este run.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Manual smoke test against real campaign data**

```bash
cd verification/cocotb
uv run streamlit run scripts/results_explorer_app.py
```

Expected: terminal prints a local URL (default `http://localhost:8501`). Open it and confirm:
- Sidebar "Campanha" defaults to `2026-07-04_campaign_03` (the most recent).
- Selecting caso `A1_tacc0p5s_load000` and run `l3_top_pwm_replay_vf_500ms` renders a multiselect with `i_alpha`, `i_beta`, `flux_alpha`, `flux_beta`, `speed`, all selected by default.
- The plot shows 5 stacked subplots, each with a dashed gray "ref" line and a solid black "vhdl" line.
- Dragging over one subplot zooms into that time range; double-clicking resets the zoom.
- The "Métricas" table below the plot shows `nrmse_i_alpha`, `nrmse_i_beta`, `mae_flux_alpha_wb`, `mae_flux_beta_wb`, `mae_speed_rad_s`.
- Switching run to `l2_vf_500ms_realts` re-renders without error.
- Press `Ctrl+C` in the terminal to stop the server.

- [ ] **Step 4: Commit**

```bash
git add verification/cocotb/pyproject.toml verification/cocotb/uv.lock \
        verification/cocotb/scripts/results_explorer_app.py
git commit -m "$(cat <<'EOF'
feat(validation): results_explorer_app — UI Streamlit do explorador

Sidebar em cascata (campanha -> caso -> run), grafico Plotly com zoom
por canal (vhdl vs referencia) e tabela de metrics.json do run.
Usa results_explorer_data.py p/ toda a logica de disco/deteccao de
canais; sem teste automatizado (UI), verificado manualmente.
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Requisito do spec | Task |
|---|---|
| Fonte de dados só `verification/results/` | Task 1 (`RESULTS_ROOT`), Global Constraints |
| Regra de ouro (disco, não manifest.json) | Task 1 (`list_cases`/`list_runs` via `iterdir`) |
| `results_explorer_data.py` sem `streamlit` | Task 1 (nenhum import de streamlit no módulo) |
| Prioridade de CSVs candidatos | Task 1 (`find_timeseries_csv`, `TIMESERIES_CSV_CANDIDATES`) |
| Detecção de canais `vhdl_*`/`ref_*`/`c_*` | Task 1 (`detect_channel_pairs`, 2 testes cobrindo ambos prefixos) |
| Coluna de tempo `t_s`/`t_us` | Task 1 (`detect_time_column`, 2 testes) |
| `metrics.json` → tabela | Task 1 (`load_metrics`) + Task 2 (`st.table`) |
| Sidebar em cascata campanha→caso→run | Task 2 (`main()`) |
| Multiselect de canais, todos por padrão | Task 2 (`st.multiselect(..., default=labels)`) |
| Gráfico com zoom (Plotly/Scattergl) | Task 2 (`_build_figure`) |
| Cache de CSV grande | Task 2 (`@st.cache_data` em `_load_csv`) |
| Erros degradam sem crash | Task 2 (`st.error`/`st.info`/`st.warning` em cada branch ausente) |
| Dependências novas via `uv add` | Task 2, Step 1 |
| Comando de execução | Task 2, Step 3 (mesmo comando do spec) |
| Sem teste automatizado da UI | Task 2 (só smoke test manual) |
| Fora de escopo (hilbin, Mestrado_latex, comparação entre casos, auth) | Nenhuma task cobre — corretamente, não fazem parte do spec |

**Placeholder scan:** nenhum `TBD`/`TODO`; todo passo tem código completo.

**Type/name consistency:** `ChannelPair(suffix, vhdl_col, ref_col)` definido em Task 1, usado com os mesmos nomes de campo em Task 2 (`pair.suffix`, `pair.vhdl_col`, `pair.ref_col`). `list_campaigns`, `list_cases`, `list_runs`, `find_timeseries_csv`, `detect_channel_pairs`, `detect_time_column`, `load_metrics`, `REPO_ROOT`, `RESULTS_ROOT` usados em Task 2 com a assinatura exata definida em Task 1.
