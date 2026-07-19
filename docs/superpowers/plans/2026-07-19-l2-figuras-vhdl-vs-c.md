# Figuras da Validação L2 (Solver VHDL vs. Modelo C) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir `l2_figures.py`, um gerador de figuras dirigido por caso que compara o solver VHDL contra o modelo C (nível L2) com métricas recalculadas e um conjunto rico de plots coloridos.

**Architecture:** Um único módulo `verification/cocotb/scripts/l2_figures.py` com (a) `compute_metrics` puro sobre arrays numpy, (b) funções de plot isoladas que recebem dados já carregados e gravam PDF+PNG, e (c) um `main()` dirigido por um manifesto que mapeia os 3 casos S0 do L2. Reusa `chapter_common.load_csv_columns` e `chapter_common.inverse_clarke` (movido de `chapter_figures`).

**Tech Stack:** Python 3, numpy, matplotlib (Agg), pytest. Executado via `uv` a partir de `verification/cocotb/`.

## Global Constraints

- **Antes de escrever qualquer código de gráfico**, o executor DEVE invocar a skill `dataviz` para calibrar paleta/legibilidade. A paleta baseline deste plano (tab10, VHDL sólido vs C tracejado) vem das figuras L1 existentes do autor; refinamentos da `dataviz` são bem-vindos desde que mantenham essa linguagem.
- **Fonte de dados canônica:** `verification/results/2026-07-04_campaign_03/S0_tacc1s_load000`. NUNCA usar `campaign_01` (parâmetros inválidos).
- **NRMSE:** definição RMS — `rms(vhdl-ref)/rms(ref)`, com `rms(x)=sqrt(mean(x^2))`. NÃO usar a definição por `range` do `fpga_vs_c.py`.
- **Coluna de tempo L2:** `t_us` (microssegundos). Converter para segundos com `1e-6`.
- **Correntes de fase:** reconstruídas de α/β por Clarke inversa (`ia+ib+ic=0`).
- **Saída:** `docs/results-chapter/figures/l2/` (raiz do repo), PDF (vetorial) + PNG (preview), mesmo nome-base.
- **Estilo:** `matplotlib.use("Agg")`, `font.family: serif`, grid leve, legenda interna, subtítulo por subplot. VHDL sólido, C tracejado.
- **Testes:** rodados de `verification/cocotb/` com `uv run pytest scripts/tests/test_l2_figures.py -q`. Testes que dependem dos dados da campanha devem `pytest.skip` se a pasta não existir.
- **Import pattern nos scripts/tests:** `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` e então `import chapter_common as cc`.

---

### Task 1: Helper compartilhado `inverse_clarke` em `chapter_common`

Move `inverse_clarke` de `chapter_figures.py` para `chapter_common.py` para reuso, mantendo `chapter_figures` funcionando via re-import.

**Files:**
- Modify: `verification/cocotb/scripts/chapter_common.py`
- Modify: `verification/cocotb/scripts/chapter_figures.py:39-47`
- Test: `verification/cocotb/scripts/tests/test_chapter_common.py`

**Interfaces:**
- Produces: `chapter_common.inverse_clarke(i_alpha: list[float], i_beta: list[float]) -> tuple[list[float], list[float], list[float]]`

- [ ] **Step 1: Write the failing test**

Adicionar ao final de `verification/cocotb/scripts/tests/test_chapter_common.py`:

```python
def test_inverse_clarke_balanced_sums_to_zero():
    import chapter_common as cc
    ia, ib, ic = cc.inverse_clarke([1.0, 2.0], [0.0, 0.5])
    # sistema equilibrado: ia+ib+ic == 0 em cada amostra
    for a, b, c in zip(ia, ib, ic):
        assert abs(a + b + c) < 1e-12
    # alpha mapeia direto para ia
    assert ia == [1.0, 2.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run (de `verification/cocotb/`): `uv run pytest scripts/tests/test_chapter_common.py::test_inverse_clarke_balanced_sums_to_zero -v`
Expected: FAIL com `AttributeError: module 'chapter_common' has no attribute 'inverse_clarke'`

- [ ] **Step 3: Implement — add to `chapter_common.py`**

Adicionar esta função em `chapter_common.py` (após os imports, antes das outras defs):

```python
def inverse_clarke(i_alpha: list[float], i_beta: list[float]) -> tuple[list[float], list[float], list[float]]:
    """Reconstroi as tres correntes de fase (ia, ib, ic) a partir de i_alpha/i_beta,
    assumindo sistema trifasico equilibrado (ia + ib + ic = 0)."""
    sqrt3_2 = 3 ** 0.5 / 2
    ia = list(i_alpha)
    ib = [-0.5 * a + sqrt3_2 * b for a, b in zip(i_alpha, i_beta)]
    ic = [-0.5 * a - sqrt3_2 * b for a, b in zip(i_alpha, i_beta)]
    return ia, ib, ic
```

- [ ] **Step 4: Update `chapter_figures.py` to reuse it**

Em `chapter_figures.py`, remover a def local `inverse_clarke` (linhas 39-47) e, logo após `import chapter_common as cc`, adicionar:

```python
inverse_clarke = cc.inverse_clarke
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_chapter_common.py scripts/tests/test_chapter_figures.py -q`
Expected: PASS (todos)

- [ ] **Step 6: Commit**

```bash
git add verification/cocotb/scripts/chapter_common.py verification/cocotb/scripts/chapter_figures.py verification/cocotb/scripts/tests/test_chapter_common.py
git commit -m "refactor(scripts): move inverse_clarke para chapter_common p/ reuso

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Núcleo de métricas `compute_metrics`

Cria `l2_figures.py` com o cálculo de métricas puro (sem matplotlib ainda).

**Files:**
- Create: `verification/cocotb/scripts/l2_figures.py`
- Test: `verification/cocotb/scripts/tests/test_l2_figures.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `l2_figures.compute_metrics(data: dict[str, list[float]]) -> dict[str, dict[str, float]]`
    onde `data` tem as chaves de coluna do CSV (`vhdl_i_alpha`, `ref_i_alpha`, ...).
    Retorna `{"i_alpha": {"nrmse","r2","max_abs"}, "i_beta": {...},
    "flux_alpha": {"mae","r2","max_abs"}, "flux_beta": {...},
    "speed": {"mae","mae_rpm","r2","max_abs"}}`.
  - `l2_figures.CAMPAIGN_DIR: Path`, `l2_figures.CASES: list[dict]` (manifesto).

- [ ] **Step 1: Write the failing test**

Criar `verification/cocotb/scripts/tests/test_l2_figures.py`:

```python
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l2_figures as l2


def test_compute_metrics_identical_is_perfect():
    n = 100
    ref = [math.sin(0.1 * i) for i in range(n)]
    data = {
        "vhdl_i_alpha": ref, "ref_i_alpha": ref,
        "vhdl_i_beta": ref, "ref_i_beta": ref,
        "vhdl_flux_alpha": ref, "ref_flux_alpha": ref,
        "vhdl_flux_beta": ref, "ref_flux_beta": ref,
        "vhdl_speed": ref, "ref_speed": ref,
    }
    m = l2.compute_metrics(data)
    assert m["i_alpha"]["nrmse"] == pytest.approx(0.0, abs=1e-12)
    assert m["i_alpha"]["r2"] == pytest.approx(1.0, abs=1e-12)
    assert m["i_alpha"]["max_abs"] == pytest.approx(0.0, abs=1e-12)
    assert m["flux_alpha"]["mae"] == pytest.approx(0.0, abs=1e-12)
    assert m["speed"]["r2"] == pytest.approx(1.0, abs=1e-12)


def test_compute_metrics_nrmse_matches_metrics_json():
    """NRMSE recalculado bate com o metrics.json da campanha (sanity-check)."""
    case = next(c for c in l2.CASES if c["id"] == "vf2s")
    csv_path = l2.CAMPAIGN_DIR / case["dir"] / case["csv"]
    mj_path = l2.CAMPAIGN_DIR / case["dir"] / "metrics.json"
    if not csv_path.is_file() or not mj_path.is_file():
        pytest.skip("dados da campanha_03 ausentes")
    import chapter_common as cc
    cols = ["vhdl_i_alpha", "ref_i_alpha", "vhdl_i_beta", "ref_i_beta",
            "vhdl_flux_alpha", "ref_flux_alpha", "vhdl_flux_beta", "ref_flux_beta",
            "vhdl_speed", "ref_speed"]
    data = cc.load_csv_columns(csv_path, cols)
    m = l2.compute_metrics(data)
    expected = json.loads(mj_path.read_text())["metrics"]
    assert m["i_alpha"]["nrmse"] == pytest.approx(expected["nrmse_i_alpha"], rel=1e-3)
    assert m["i_beta"]["nrmse"] == pytest.approx(expected["nrmse_i_beta"], rel=1e-3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scripts/tests/test_l2_figures.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'l2_figures'`

- [ ] **Step 3: Create `l2_figures.py` with metrics core + manifest**

```python
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chapter_common as cc  # noqa: E402  (load_csv_columns, inverse_clarke)

# ── Caminhos ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_DIR = REPO_ROOT / "verification/results/2026-07-04_campaign_03/S0_tacc1s_load000"
DEFAULT_OUT = REPO_ROOT / "docs/results-chapter/figures/l2"

# ── Manifesto dos casos ───────────────────────────────────────────────────────
# tipo: "sine" (regime) ou "vf" (rampa). Define o conjunto de plots.
CASES = [
    {"id": "sine",  "dir": "l2_sine_60hz_realts", "csv": "sine_vhdl_vs_c.csv",
     "tipo": "sine", "label": "Seno 60 Hz",
     "zoom": [(1.0, 4.0, "Regime permanente", "#2ca02c")]},   # ms (ver t_ms)
    {"id": "vf50ms", "dir": "l2_vf_50ms_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 50 ms",
     "plots": ["overlay", "residual"],   # override: transitorio curto
     "zoom": []},
    {"id": "vf2s", "dir": "l2_vf_2s_realts", "csv": "vf_vhdl_vs_c.csv",
     "tipo": "vf", "label": "V/f 2 s",
     "zoom": [(1900.0, 2000.0, "Regime permanente", "#2ca02c")],  # ms
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_l2_figures.py -v`
Expected: PASS (2 testes; o de sanity pode `skip` se dados ausentes, mas na árvore atual os dados existem → PASS)

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l2_figures.py verification/cocotb/scripts/tests/test_l2_figures.py
git commit -m "feat(l2_figures): nucleo de metricas (NRMSE-RMS/R2/max/MAE) + manifesto

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Estilo, `save_fig` e `plot_overlay`

Adiciona a configuração de estilo, o gravador PDF+PNG e o plot principal (overlay).

**Files:**
- Modify: `verification/cocotb/scripts/l2_figures.py`
- Test: `verification/cocotb/scripts/tests/test_l2_figures.py`

**Interfaces:**
- Consumes: `compute_metrics`, `cc.inverse_clarke`.
- Produces:
  - `l2_figures.load_case(case: dict) -> tuple[np.ndarray, dict]` → `(t_ms, data)`.
  - `l2_figures.save_fig(fig, out_dir: Path, name: str) -> None` (grava `name.pdf` e `name.png`).
  - `l2_figures.plot_overlay(t_ms, data, case, out_dir) -> None`.

**Nota:** invocar a skill `dataviz` antes deste passo.

- [ ] **Step 1: Write the failing smoke test**

Adicionar a `test_l2_figures.py`:

```python
def test_plot_overlay_creates_files(tmp_path):
    n = 200
    t = [i for i in range(n)]  # us
    ramp = [i / n for i in range(n)]
    data = {
        "t_us": t,
        "vhdl_i_alpha": ramp, "vhdl_i_beta": ramp,
        "ref_i_alpha": ramp, "ref_i_beta": ramp,
        "vhdl_flux_alpha": ramp, "vhdl_flux_beta": ramp,
        "ref_flux_alpha": ramp, "ref_flux_beta": ramp,
        "vhdl_speed": ramp, "ref_speed": ramp,
    }
    import numpy as np
    t_ms = np.asarray(t) * 1e-3
    case = {"id": "smoke", "label": "Smoke", "tipo": "vf", "zoom": []}
    l2.plot_overlay(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_Smoke_Overlay.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L2_Smoke_Overlay.png").stat().st_size > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scripts/tests/test_l2_figures.py::test_plot_overlay_creates_files -v`
Expected: FAIL com `AttributeError: module 'l2_figures' has no attribute 'plot_overlay'`

- [ ] **Step 3: Implement — add style + save_fig + load_case + plot_overlay**

Adicionar ao topo de `l2_figures.py` (após `import numpy as np`):

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({
    "font.family": "serif",
    "axes.grid": True,
    "grid.color": "#d9d9d9",
    "grid.linewidth": 0.5,
    "axes.edgecolor": "black",
    "figure.dpi": 120,
})

# Paleta por fase (tab10) — VHDL solido, C tracejado
PHASE_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c")  # ia, ib, ic
VHDL_STYLE = {"linestyle": "-", "linewidth": 1.3}
REF_STYLE = {"linestyle": "--", "linewidth": 1.3, "alpha": 0.85}
```

Adicionar as funções (após `compute_metrics`):

```python
def _fig_id(case: dict) -> str:
    return {"sine": "Sine", "vf50ms": "VF50ms", "vf2s": "VF2s"}.get(
        case["id"], case["id"].capitalize())


def load_case(case: dict, campaign: Path = CAMPAIGN_DIR) -> tuple[np.ndarray, dict]:
    csv_path = campaign / case["dir"] / case["csv"]
    data = cc.load_csv_columns(csv_path, CSV_COLS)
    t_ms = np.asarray(data["t_us"], dtype=float) * 1e-3
    return t_ms, data


def save_fig(fig, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


def plot_overlay(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """3 paineis: correntes trifasicas, modulo do fluxo, velocidade (VHDL vs C)."""
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
        axes[0].plot(t, ref_i[k], color=PHASE_COLORS[k], **REF_STYLE)
        axes[0].plot(t, vhdl_i[k], color=PHASE_COLORS[k], label=labels[k], **VHDL_STYLE)
    axes[0].set_ylabel("Corrente [A]")
    axes[0].set_title(f"L2 — {case['label']}: correntes (— VHDL, - - C)")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    axes[1].plot(t, ref_flux, color="#d62728", **REF_STYLE, label="C")
    axes[1].plot(t, vhdl_flux, color="#1f77b4", **VHDL_STYLE, label="VHDL")
    axes[1].set_ylabel(r"$|\psi_r|$ [Wb]")
    axes[1].legend(loc="upper right", fontsize=8)

    axes[2].plot(t, np.asarray(data["ref_speed"]), color="#d62728", **REF_STYLE, label="C")
    axes[2].plot(t, np.asarray(data["vhdl_speed"]), color="#1f77b4", **VHDL_STYLE, label="VHDL")
    axes[2].set_ylabel(r"$\omega$ [rad/s]")
    axes[2].set_xlabel("Tempo [s]")
    axes[2].legend(loc="upper right", fontsize=8)

    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Overlay")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest scripts/tests/test_l2_figures.py::test_plot_overlay_creates_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l2_figures.py verification/cocotb/scripts/tests/test_l2_figures.py
git commit -m "feat(l2_figures): estilo, save_fig (PDF+PNG) e plot_overlay

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `plot_lissajous` e `plot_phase_zoom`

**Files:**
- Modify: `verification/cocotb/scripts/l2_figures.py`
- Test: `verification/cocotb/scripts/tests/test_l2_figures.py`

**Interfaces:**
- Consumes: `save_fig`, `_fig_id`, `cc.inverse_clarke`.
- Produces:
  - `l2_figures.plot_lissajous(t_ms, data, case, out_dir) -> None`
  - `l2_figures.plot_phase_zoom(t_ms, data, case, out_dir) -> None`

- [ ] **Step 1: Write the failing smoke test**

Adicionar a `test_l2_figures.py` uma fixture reutilizável e dois testes:

```python
import numpy as np


def _synthetic_case(tmp_path, tipo="sine", zoom=None):
    n = 600
    t_us = np.linspace(0, 5000, n)  # 0..5 ms
    ang = 2 * np.pi * 60 * (t_us * 1e-6)
    ia = np.cos(ang)
    ib = np.cos(ang - 2 * np.pi / 3)
    # de volta a alpha/beta (Clarke direta) para alimentar o CSV-like dict
    i_alpha = ia
    i_beta = (ia + 2 * ib) / np.sqrt(3)
    data = {
        "t_us": t_us.tolist(),
        "vhdl_i_alpha": i_alpha.tolist(), "vhdl_i_beta": i_beta.tolist(),
        "ref_i_alpha": (i_alpha * 1.001).tolist(), "ref_i_beta": (i_beta * 1.001).tolist(),
        "vhdl_flux_alpha": (0.5 * i_alpha).tolist(), "vhdl_flux_beta": (0.5 * i_beta).tolist(),
        "ref_flux_alpha": (0.5 * i_alpha).tolist(), "ref_flux_beta": (0.5 * i_beta).tolist(),
        "vhdl_speed": np.linspace(0, 180, n).tolist(),
        "ref_speed": np.linspace(0, 180, n).tolist(),
    }
    case = {"id": "sine", "label": "Seno", "tipo": tipo, "zoom": zoom or [(1.0, 4.0, "Regime", "#2ca02c")]}
    return t_us * 1e-3, data, case


def test_plot_lissajous_creates_files(tmp_path):
    t_ms, data, case = _synthetic_case(tmp_path)
    l2.plot_lissajous(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_Sine_Lissajous.pdf").stat().st_size > 0


def test_plot_phase_zoom_creates_files(tmp_path):
    t_ms, data, case = _synthetic_case(tmp_path)
    l2.plot_phase_zoom(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_Sine_PhaseZoom.pdf").stat().st_size > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest scripts/tests/test_l2_figures.py -k "lissajous or phase_zoom" -v`
Expected: FAIL com `AttributeError` para `plot_lissajous`/`plot_phase_zoom`

- [ ] **Step 3: Implement — add both functions**

```python
def _subsample(n: int, target: int = 5000) -> slice:
    step = max(1, n // target)
    return slice(None, None, step)


def plot_lissajous(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Trajetoria espaco-vetorial i_beta x i_alpha (VHDL vs C)."""
    s = _subsample(len(t_ms))
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(np.asarray(data["ref_i_alpha"])[s], np.asarray(data["ref_i_beta"])[s],
            color="#d62728", label="C", **REF_STYLE)
    ax.plot(np.asarray(data["vhdl_i_alpha"])[s], np.asarray(data["vhdl_i_beta"])[s],
            color="#1f77b4", label="VHDL", **VHDL_STYLE)
    ax.set_xlabel(r"$i_\alpha$ [A]")
    ax.set_ylabel(r"$i_\beta$ [A]")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(f"L2 — {case['label']}: trajetória $i_\\beta \\times i_\\alpha$")
    ax.legend(loc="upper right", fontsize=9)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Lissajous")


def plot_phase_zoom(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Corrente ia completa + regioes sombreadas + paineis de zoom (estilo L1)."""
    t = t_ms / 1000.0  # s
    vhdl_ia = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])[0]
    ref_ia = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])[0]
    vhdl_ia, ref_ia = np.asarray(vhdl_ia), np.asarray(ref_ia)

    zooms = case.get("zoom", [])
    nz = len(zooms)
    fig, axes = plt.subplots(1 + nz, 1, figsize=(8, 3 + 2.2 * nz))
    if nz == 0:
        axes = [axes]
    top = axes[0]
    top.plot(t, ref_ia, color="#d62728", label="$i_a$ (C)", **REF_STYLE)
    top.plot(t, vhdl_ia, color="#1f77b4", label="$i_a$ (VHDL)", **VHDL_STYLE)
    for (a_ms, b_ms, lbl, col) in zooms:
        top.axvspan(a_ms / 1000.0, b_ms / 1000.0, color=col, alpha=0.15, label=lbl)
    top.set_ylabel("$i_a$ [A]")
    top.set_xlabel("Tempo [s]")
    top.set_title(f"L2 — {case['label']}: visão completa e zoom")
    top.legend(loc="upper right", fontsize=8)

    for ax, (a_ms, b_ms, lbl, col) in zip(axes[1:], zooms):
        a, b = a_ms / 1000.0, b_ms / 1000.0
        mask = (t >= a) & (t <= b)
        ax.plot(t[mask], ref_ia[mask], color="#d62728", label="C", **REF_STYLE)
        ax.plot(t[mask], vhdl_ia[mask], color="#1f77b4", label="VHDL", **VHDL_STYLE)
        ax.set_title(f"{lbl}: {a_ms:.0f}–{b_ms:.0f} ms", fontsize=10)
        ax.set_ylabel("$i_a$ [A]")
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("Tempo [s]")
    fig.tight_layout()
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_PhaseZoom")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_l2_figures.py -k "lissajous or phase_zoom" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l2_figures.py verification/cocotb/scripts/tests/test_l2_figures.py
git commit -m "feat(l2_figures): plot_lissajous e plot_phase_zoom

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `plot_residual` e `plot_window_nrmse`

**Files:**
- Modify: `verification/cocotb/scripts/l2_figures.py`
- Test: `verification/cocotb/scripts/tests/test_l2_figures.py`

**Interfaces:**
- Consumes: `save_fig`, `_fig_id`, `_nrmse`, `cc.inverse_clarke`.
- Produces:
  - `l2_figures.plot_residual(t_ms, data, case, out_dir) -> None`
  - `l2_figures.plot_window_nrmse(t_ms, data, case, out_dir) -> None`

- [ ] **Step 1: Write the failing smoke test**

```python
def test_plot_residual_creates_files(tmp_path):
    t_ms, data, case = _synthetic_case(tmp_path)
    l2.plot_residual(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_Sine_Residual.pdf").stat().st_size > 0


def test_plot_window_nrmse_creates_files(tmp_path):
    t_ms, data, case = _synthetic_case(tmp_path)
    case = dict(case, id="vf2s", label="V/f 2 s",
                windows_s=[(0.0, 0.002), (0.002, 0.005)])
    l2.plot_window_nrmse(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_VF2s_WindowNRMSE.pdf").stat().st_size > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest scripts/tests/test_l2_figures.py -k "residual or window_nrmse" -v`
Expected: FAIL com `AttributeError`

- [ ] **Step 3: Implement — add both functions**

```python
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
    axes[0].set_title(f"L2 — {case['label']}: erro VHDL − C")
    axes[0].legend(loc="upper right", ncol=3, fontsize=8)

    err_w = np.asarray(data["vhdl_speed"]) - np.asarray(data["ref_speed"])
    axes[1].plot(t, err_w, color="#9467bd", linewidth=1.0, label=r"$\varepsilon_\omega$")
    axes[1].axhline(0.0, color="0.5", linewidth=0.6)
    axes[1].set_ylabel("Erro veloc. [rad/s]")
    axes[1].set_xlabel("Tempo [s]")
    axes[1].legend(loc="upper right", fontsize=8)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_Residual")


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
    ax.bar(x - w / 2, nrmse_a, w, color="#1f77b4", label=r"$i_\alpha$")
    ax.bar(x + w / 2, nrmse_b, w, color="#ff7f0e", label=r"$i_\beta$")
    ax.set_xticks(x); ax.set_xticklabels(xlabels)
    ax.set_xlabel("Janela [s]")
    ax.set_ylabel("NRMSE [%]")
    ax.set_title(f"L2 — {case['label']}: NRMSE por janela")
    ax.legend(fontsize=9)
    save_fig(fig, out_dir, f"HIL_L2_{_fig_id(case)}_WindowNRMSE")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_l2_figures.py -k "residual or window_nrmse" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l2_figures.py verification/cocotb/scripts/tests/test_l2_figures.py
git commit -m "feat(l2_figures): plot_residual e plot_window_nrmse

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Driver `main()` + `l2_metrics.json` + geração real

Amarra tudo: percorre o manifesto, gera o conjunto de plots por tipo de cenário, grava `l2_metrics.json`, e roda de verdade sobre a campaign_03.

**Files:**
- Modify: `verification/cocotb/scripts/l2_figures.py`
- Test: `verification/cocotb/scripts/tests/test_l2_figures.py`

**Interfaces:**
- Consumes: todas as funções `plot_*`, `compute_metrics`, `load_case`.
- Produces: `l2_figures.generate_case(case, out_dir, campaign) -> dict` (retorna métricas do caso); `l2_figures.main(argv=None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_generate_case_end_to_end(tmp_path):
    case = next(c for c in l2.CASES if c["id"] == "vf2s")
    if not (l2.CAMPAIGN_DIR / case["dir"] / case["csv"]).is_file():
        pytest.skip("dados da campanha_03 ausentes")
    metrics = l2.generate_case(case, tmp_path, l2.CAMPAIGN_DIR)
    assert (tmp_path / "HIL_L2_VF2s_Overlay.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L2_VF2s_WindowNRMSE.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L2_VF2s_Residual.pdf").stat().st_size > 0
    assert 0.0 < metrics["i_alpha"]["nrmse"] < 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scripts/tests/test_l2_figures.py::test_generate_case_end_to_end -v`
Expected: FAIL com `AttributeError: ... 'generate_case'`

- [ ] **Step 3: Implement — add generate_case + main**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest scripts/tests/test_l2_figures.py::test_generate_case_end_to_end -v`
Expected: PASS

- [ ] **Step 5: Run the full test file**

Run: `uv run pytest scripts/tests/test_l2_figures.py -q`
Expected: PASS (todos)

- [ ] **Step 6: Generate the real figures**

Run (de `verification/cocotb/`): `uv run python scripts/l2_figures.py`
Expected: cria PDFs+PNGs em `docs/results-chapter/figures/l2/` para os 3 casos + `l2_metrics.json`. Verificar:

```bash
ls -la ../../docs/results-chapter/figures/l2/
```

Esperado: `HIL_L2_Sine_Overlay.{pdf,png}`, `HIL_L2_Sine_Lissajous.*`, `HIL_L2_Sine_PhaseZoom.*`, `HIL_L2_VF50ms_Overlay.*`, `HIL_L2_VF50ms_Residual.*`, `HIL_L2_VF2s_Overlay.*`, `HIL_L2_VF2s_Lissajous.*`, `HIL_L2_VF2s_Residual.*`, `HIL_L2_VF2s_PhaseZoom.*`, `HIL_L2_VF2s_WindowNRMSE.*`, `l2_metrics.json`.

- [ ] **Step 7: Commit**

```bash
git add verification/cocotb/scripts/l2_figures.py verification/cocotb/scripts/tests/test_l2_figures.py docs/results-chapter/figures/l2/
git commit -m "feat(l2_figures): driver main, l2_metrics.json e figuras L2 geradas

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notas de execução

- **Revisão visual:** após o Step 6 da Task 6, PARAR e mostrar os PNGs ao usuário para aprovação estética antes de qualquer ajuste fino de paleta/layout (a skill `dataviz` orienta refinamentos).
- O cenário `sine` tem ~384k linhas; `load_case` + `plot_overlay` podem levar alguns segundos. `plot_lissajous` subamostra para ~5000 pontos (tamanho de PDF controlado). Se o overlay do seno ficar denso demais visualmente, considerar recorte temporal (ex.: primeiros 3 ciclos) — decisão de refino pós-revisão, não bloqueia o plano.
- A janela de zoom do seno usa 1–4 ms; a do vf2s usa 1900–2000 ms. Ajustáveis no manifesto `CASES`.
```
