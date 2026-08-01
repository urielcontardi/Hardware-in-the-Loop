# L4-B — Validação Independente em PSIM: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new validation comparison ("L4-B": FPGA real telemetry vs. an
independent, complete V/f+carrier+NPC+motor reproduction in PSIM) to the
dissertation — a figure-generation script, a new Cap.3 methodology
subsection, and a new Cap.4 results section, for the 6-case reduced matrix
(S0, A1, A3, A5, B1, B2).

**Architecture:** A new script `l4b_figures.py`, sibling to the existing
`l4_figures.py`/`l2_figures.py` in `verification/cocotb/scripts/`, reads the
already-merged `.npz` files (`fpga_*`/`psim_*` fields — `psim_*` was added by
`psim_csv_to_npz.py` in prior sessions) plus the raw PSIM CSV exports and raw
FPGA `.hilbin` captures, and emits PDF/PNG figures + a LaTeX table fragment
following the exact naming/visual conventions the existing L2/L4 figure
pipeline already uses. Two hand-written LaTeX edits (Cap.3, Cap.4) then
consume those artifacts.

**Tech Stack:** Python 3.12, numpy, pandas, matplotlib (Agg backend), pytest;
LaTeX (existing `Mestrado_latex` project, `quadro`/`table`/booktabs style).

## Global Constraints

- Only the PSIM-**native motor** branch (`Iu/Iv/Iw/motorSpeed`, merged as
  `psim_ia/psim_ib/psim_speed`) is used — never the C-model/DLL branch.
- **`psim_ia`/`psim_ib` are already an α/β (Clarke) pair**, not raw phase
  currents (confirmed: `psim_csv_to_npz.py` computes `ia = -Iu`,
  `ib = -(Iv-Iw)/√3`) — every figure that shows three-phase currents must
  apply `chapter_common.inverse_clarke()` to `psim_ia/psim_ib` exactly as it
  already does for `fpga_ia/fpga_ib`. Do not skip this transform for PSIM.
- **No flux panel anywhere** — the PSIM native motor block does not expose
  rotor flux. This is a hard technical constraint (confirmed: no
  `psim_flux_a`/`psim_flux_b` keys exist in any merged `.npz`), not a style
  choice.
- **`psim_t` is not on the same time grid as `fpga_t`/`cmod_t`**, and for the
  `regime` window PSIM data stops ~0.15s short of the FPGA/C window
  (`[2.6534, 3.0]` vs `[2.6534, 3.1534]` for A3, and similarly for other
  cases with `Total Time` capped by what was actually simulated in PSIM).
  Every windowed figure/metric must interpolate PSIM onto the FPGA time grid,
  **clipped to the overlapping range** — never assume a shared time axis.
- Campaign root is `verification/results/2026-07-25_campaign_l4_final`
  (symlink to `2026-07-25_l4_repeat/r1` — use the symlinked name, it's what
  the rest of the pipeline/dissertation references).
- The B1 "stall" episode (an earlier session's mistake showing the wrong
  DLL/C-model branch) must not be mentioned anywhere in generated text.
- The integration-method (Backward Euler vs. Trapezoidal) finding is scoped
  to **S0 only** — never imply it was tested systematically across all 6
  cases.
- Do not attempt to formalize the C-mock (`hil_fullstack_mock.py`) vs. real
  FPGA comparison — out of scope per the design spec.
- Do not touch the pre-existing L1 (PSIM vs. C) section's known data gaps
  (`fig:PSIM_Results2` duplicate, missing `simPWM02/03.txt`) — unrelated,
  out of scope.

---

## Reference data (verified on disk, not assumed)

Real per-case parameters (`verification/results/2026-07-25_campaign_l4_final/<Caso>_l4/l4_pwm_replay/capture/metrics.json`, and the raw PSIM CSVs already produced in prior sessions):

| Caso | `dir` | PSIM CSV (relative to repo root) |
|---|---|---|
| S0 | `S0_l4` | `extras/induction-motor-model/data/S0/S0_1us_trapezoidal.csv` |
| A1 | `A1_l4` | `extras/induction-motor-model/data/AX/A1_1us.csv` |
| A3 | `A3_l4` | `extras/induction-motor-model/data/AX/A3_1us.csv` |
| A5 | `A5_l4` | `extras/induction-motor-model/data/AX/A5_1us.csv` |
| B1 | `B1_l4` | `extras/induction-motor-model/data/BX/B1_500ns.csv` |
| B2 | `B2_l4` | `extras/induction-motor-model/data/BX/B2_500ns.csv` |

Merged `.npz` field names (verified via `np.load(...).files` on
`A3_l4/l4_pwm_replay/capture/regime.npz`): `fpga_t, fpga_ia, fpga_ib,
fpga_flux_a, fpga_flux_b, fpga_speed, cmod_t, cmod_ia, cmod_ib, cmod_flux_a,
cmod_flux_b, cmod_speed, psim_t, psim_ia, psim_ib, psim_speed`. Same set in
`partida.npz`.

---

### Task 1: Time-alignment helper (PSIM onto FPGA grid, clipped)

**Files:**
- Create: `verification/cocotb/scripts/l4b_figures.py`
- Test: `verification/cocotb/scripts/test_l4b_figures.py`

**Interfaces:**
- Produces: `_overlap_mask_and_grid(fpga_t: np.ndarray, psim_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]` — returns `(mask, t_common)` where `mask` selects into any FPGA-grid array and `t_common = fpga_t[mask]`, clipped to where both series have data.

- [ ] **Step 1: Write the failing test**

```python
# verification/cocotb/scripts/test_l4b_figures.py
import numpy as np
from l4b_figures import _overlap_mask_and_grid


def test_overlap_mask_and_grid_clips_to_shorter_series():
    fpga_t = np.linspace(0.0, 1.0, 11)   # 0.0, 0.1, ..., 1.0
    psim_t = np.linspace(0.0, 0.6, 601)  # 0.0 .. 0.6, stops early (like regime window)
    mask, t_common = _overlap_mask_and_grid(fpga_t, psim_t)
    assert t_common.max() <= 0.6 + 1e-9
    assert t_common.min() >= 0.0 - 1e-9
    assert mask.sum() == t_common.size
    assert np.array_equal(fpga_t[mask], t_common)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd verification/cocotb && source .venv/bin/activate
python3 -m pytest scripts/test_l4b_figures.py::test_overlap_mask_and_grid_clips_to_shorter_series -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'l4b_figures'` (file doesn't exist yet).

- [ ] **Step 3: Create `l4b_figures.py` with the module docstring, imports, and this function**

```python
#!/usr/bin/env python3
"""Gera figuras L4-B: FPGA real vs. reprodução independente completa em PSIM
(motor de indução nativo do PSIM, nao o modelo C/DLL embutido no mesmo
schematic). Ve docs/superpowers/specs/2026-08-01-l4b-psim-validacao-independente-design.md.

Le os .npz ja mesclados (fpga_*/psim_*, ver psim_csv_to_npz.py) para as
figuras de janela (partida/regime), e le o .hilbin bruto + o CSV bruto do
PSIM para a figura de visao geral (janela completa).

psim_ia/psim_ib sao um par alpha/beta (ver psim_csv_to_npz.py), nao fase
crua -- toda figura trifasica aplica chapter_common.inverse_clarke() neles,
igual ja e feito para fpga_ia/fpga_ib.

Sem painel de fluxo: o motor nativo do PSIM nao expoe fluxo do rotor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l2_figures as eng                # noqa: E402
import chapter_common as cc              # noqa: E402
import hilbin_vs_c as H                  # noqa: E402
import psim_csv_to_npz as psim_mod       # noqa: E402


def _overlap_mask_and_grid(fpga_t: np.ndarray, psim_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Clip fpga_t to the range where psim_t also has data.

    Returns (mask, t_common): mask selects into any array sampled on the
    fpga_t grid, t_common = fpga_t[mask].
    """
    t_lo = max(float(fpga_t.min()), float(psim_t.min()))
    t_hi = min(float(fpga_t.max()), float(psim_t.max()))
    mask = (fpga_t >= t_lo) & (fpga_t <= t_hi)
    return mask, fpga_t[mask]


if __name__ == "__main__":
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/test_l4b_figures.py::test_overlap_mask_and_grid_clips_to_shorter_series -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/l4b_figures.py verification/cocotb/scripts/test_l4b_figures.py
git commit -m "feat(l4b): add PSIM/FPGA time-alignment helper"
```

---

### Task 2: Segment loader (builds `eng`-compatible data dict)

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`
- Test: `verification/cocotb/scripts/test_l4b_figures.py`

**Interfaces:**
- Consumes: `_overlap_mask_and_grid` (Task 1).
- Produces: `load_l4b_segment(case: dict, seg: str, campaign: Path) -> tuple[np.ndarray, dict]` — `t_ms` (milliseconds, matching `l2_figures.py`'s convention) and a `data` dict with keys `vhdl_i_alpha, vhdl_i_beta, vhdl_speed, ref_i_alpha, ref_i_beta, ref_speed` (FPGA=`vhdl`, PSIM=`ref`, same naming `eng.plot_lissajous`/`eng.plot_residual` expect). `case` dict must have key `"dir"` (e.g. `"A3_l4"`).

- [ ] **Step 1: Write the failing test**

```python
def test_load_l4b_segment_a3_regime_has_expected_shape_and_units():
    from pathlib import Path
    campaign = Path("/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-25_campaign_l4_final")
    case = {"id": "A3", "dir": "A3_l4"}
    t_ms, data = load_l4b_segment(case, "regime", campaign)
    assert t_ms.max() > t_ms.min()
    assert t_ms.max() <= 3000.0 + 1.0  # PSIM regime data stops at ~3.0s -> 3000ms
    for key in ("vhdl_i_alpha", "vhdl_i_beta", "vhdl_speed", "ref_i_alpha", "ref_i_beta", "ref_speed"):
        assert data[key].shape == t_ms.shape
    # sanity: speeds should be in the same ballpark (both near sync ~187 rad/s in regime)
    assert abs(float(np.mean(data["vhdl_speed"])) - float(np.mean(data["ref_speed"]))) < 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/test_l4b_figures.py::test_load_l4b_segment_a3_regime_has_expected_shape_and_units -v`
Expected: FAIL with `NameError`/`ImportError` (`load_l4b_segment` not defined).

- [ ] **Step 3: Add the function to `l4b_figures.py`** (after `_overlap_mask_and_grid`)

```python
def load_l4b_segment(case: dict, seg: str, campaign: Path) -> tuple[np.ndarray, dict]:
    """Load one partida/regime .npz, align PSIM onto the FPGA/C time grid.

    Returns (t_ms, data): data has vhdl_i_alpha/vhdl_i_beta/vhdl_speed
    (FPGA, clipped to PSIM's coverage) and ref_i_alpha/ref_i_beta/ref_speed
    (PSIM, interpolated onto the clipped FPGA grid).
    """
    npz_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / f"{seg}.npz"
    d = np.load(npz_path)
    fpga_t = np.asarray(d["fpga_t"], dtype=float)
    psim_t = np.asarray(d["psim_t"], dtype=float)
    mask, t_common = _overlap_mask_and_grid(fpga_t, psim_t)
    data = {
        "vhdl_i_alpha": np.asarray(d["fpga_ia"])[mask],
        "vhdl_i_beta": np.asarray(d["fpga_ib"])[mask],
        "vhdl_speed": np.asarray(d["fpga_speed"])[mask],
        "ref_i_alpha": np.interp(t_common, psim_t, np.asarray(d["psim_ia"])),
        "ref_i_beta": np.interp(t_common, psim_t, np.asarray(d["psim_ib"])),
        "ref_speed": np.interp(t_common, psim_t, np.asarray(d["psim_speed"])),
    }
    t_ms = t_common * 1000.0
    return t_ms, data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/test_l4b_figures.py::test_load_l4b_segment_a3_regime_has_expected_shape_and_units -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py verification/cocotb/scripts/test_l4b_figures.py
git commit -m "feat(l4b): add segment loader aligning PSIM onto FPGA time grid"
```

---

### Task 3: Flux-free metrics

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`
- Test: `verification/cocotb/scripts/test_l4b_figures.py`

**Interfaces:**
- Consumes: a `data` dict shaped like `load_l4b_segment`'s output (Task 2).
- Produces: `compute_metrics_l4b(data: dict) -> dict[str, float]` with keys `nrmse_i_alpha_pct, nrmse_i_beta_pct, mae_speed_rad_s`.

- [ ] **Step 1: Write the failing test**

```python
def test_compute_metrics_l4b_zero_for_identical_series():
    data = {
        "vhdl_i_alpha": np.array([1.0, 2.0, 3.0, 4.0]),
        "vhdl_i_beta": np.array([-1.0, 0.0, 1.0, 2.0]),
        "vhdl_speed": np.array([100.0, 101.0, 102.0, 103.0]),
        "ref_i_alpha": np.array([1.0, 2.0, 3.0, 4.0]),
        "ref_i_beta": np.array([-1.0, 0.0, 1.0, 2.0]),
        "ref_speed": np.array([100.0, 101.0, 102.0, 103.0]),
    }
    m = compute_metrics_l4b(data)
    assert m["nrmse_i_alpha_pct"] == 0.0
    assert m["nrmse_i_beta_pct"] == 0.0
    assert m["mae_speed_rad_s"] == 0.0


def test_compute_metrics_l4b_nonzero_for_offset_series():
    data = {
        "vhdl_i_alpha": np.array([1.0, 2.0, 3.0, 4.0]),
        "vhdl_i_beta": np.array([-1.0, 0.0, 1.0, 2.0]),
        "vhdl_speed": np.array([100.0, 101.0, 102.0, 103.0]),
        "ref_i_alpha": np.array([1.0, 2.0, 3.0, 4.0]) + 1.0,
        "ref_i_beta": np.array([-1.0, 0.0, 1.0, 2.0]),
        "ref_speed": np.array([100.0, 101.0, 102.0, 103.0]) + 2.0,
    }
    m = compute_metrics_l4b(data)
    assert m["nrmse_i_alpha_pct"] > 0.0
    assert m["nrmse_i_beta_pct"] == 0.0
    assert m["mae_speed_rad_s"] == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/test_l4b_figures.py -k compute_metrics_l4b -v`
Expected: FAIL (`compute_metrics_l4b` not defined).

- [ ] **Step 3: Add the functions to `l4b_figures.py`**

```python
def _nrmse_pct(dut: np.ndarray, ref: np.ndarray) -> float:
    """RMSE(dut-ref) normalized by the peak-to-peak range of ref, as a percentage."""
    rmse = float(np.sqrt(np.mean((dut - ref) ** 2)))
    span = float(np.ptp(ref))
    return 100.0 * rmse / span if span > 0 else float("nan")


def _mae(dut: np.ndarray, ref: np.ndarray) -> float:
    return float(np.mean(np.abs(dut - ref)))


def compute_metrics_l4b(data: dict) -> dict[str, float]:
    """NRMSE (%) for i_alpha/i_beta, MAE for speed. No flux metric: the PSIM
    native motor block doesn't expose rotor flux."""
    return {
        "nrmse_i_alpha_pct": _nrmse_pct(data["vhdl_i_alpha"], data["ref_i_alpha"]),
        "nrmse_i_beta_pct": _nrmse_pct(data["vhdl_i_beta"], data["ref_i_beta"]),
        "mae_speed_rad_s": _mae(data["vhdl_speed"], data["ref_speed"]),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/test_l4b_figures.py -k compute_metrics_l4b -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py verification/cocotb/scripts/test_l4b_figures.py
git commit -m "feat(l4b): add flux-free NRMSE/MAE metrics"
```

---

### Task 4: LaTeX table-fragment renderer

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`
- Test: `verification/cocotb/scripts/test_l4b_figures.py`

**Interfaces:**
- Consumes: `all_metrics: dict[str, dict[str, dict[str, float]]]` shaped `{case_id: {"partida": <compute_metrics_l4b output>, "regime": <compute_metrics_l4b output>}}`.
- Produces: `render_l4b_table(all_metrics: dict) -> str` — table-body-only LaTeX fragment (no `\begin{table}`/`\caption`/`\label` wrapper, matching every other generated `.tex` fragment in this repo — those stay hand-written in `4-Resultados.tex`).

- [ ] **Step 1: Write the failing test**

```python
def test_render_l4b_table_has_expected_structure():
    all_metrics = {
        "S0": {"partida": {"nrmse_i_alpha_pct": 1.23, "nrmse_i_beta_pct": 2.34, "mae_speed_rad_s": 0.01},
               "regime": {"nrmse_i_alpha_pct": 0.5, "nrmse_i_beta_pct": 0.6, "mae_speed_rad_s": 0.001}},
    }
    tex = render_l4b_table(all_metrics)
    assert tex.startswith("\\begin{tabular}")
    assert tex.rstrip().endswith("\\end{tabular}")
    assert "S0 &" in tex
    assert "1.23\\%" in tex
    assert "\\toprule" in tex and "\\bottomrule" in tex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/test_l4b_figures.py::test_render_l4b_table_has_expected_structure -v`
Expected: FAIL (`render_l4b_table` not defined).

- [ ] **Step 3: Add the functions to `l4b_figures.py`**

```python
def _fmt_pct(x: float) -> str:
    return f"{x:.2f}\\%"


def _fmt_sci(x: float) -> str:
    return f"{x:.3g}"


def render_l4b_table(all_metrics: dict[str, dict[str, dict[str, float]]]) -> str:
    """Table-body fragment only (no \\begin{table}/\\caption/\\label wrapper --
    those are hand-written in 4-Resultados.tex, matching tab:l4-metricas'
    style; see chapter_tables.py::_render_metricas_table for the sibling
    pattern this mirrors)."""
    lines = [
        "\\begin{tabular}{l" + "c" * 6 + "}",
        "\\toprule",
        " & \\multicolumn{3}{c}{Partida} & \\multicolumn{3}{c}{Regime} \\\\",
        "Caso & $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] "
        "& $i_\\alpha$ [\\%] & $i_\\beta$ [\\%] & $\\omega$ [rad/s] \\\\",
        "\\midrule",
    ]
    for case_id, windows in all_metrics.items():
        p = windows.get("partida", {})
        r = windows.get("regime", {})
        cells = [
            _fmt_pct(p.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(p.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(p.get("mae_speed_rad_s", float("nan"))),
            _fmt_pct(r.get("nrmse_i_alpha_pct", float("nan"))),
            _fmt_pct(r.get("nrmse_i_beta_pct", float("nan"))),
            _fmt_sci(r.get("mae_speed_rad_s", float("nan"))),
        ]
        lines.append(f"{case_id} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/test_l4b_figures.py::test_render_l4b_table_has_expected_structure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py verification/cocotb/scripts/test_l4b_figures.py
git commit -m "feat(l4b): add LaTeX metrics table fragment renderer"
```

---

### Task 5: Windowed overlay figure (`plot_overlay_l4b`)

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`

**Interfaces:**
- Consumes: `t_ms`/`data` from `load_l4b_segment` (Task 2); `case: dict` with keys `id, label, fig_prefix` (and optionally `fig_id`, `labels`).
- Produces: `plot_overlay_l4b(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None` — writes `{out_dir}/{fig_prefix}_{fig_id}_Overlay.{pdf,png}`. Also produces `_seg_case(case: dict, seg: str) -> dict` (per-segment case copy, used by Task 6 too).

No automated test for this task (matplotlib figure output — verified by manual inspection in Step 3). This mirrors how `l2_figures.py`/`l4_figures.py` plotting functions are verified in this codebase (no unit tests exist for them either).

- [ ] **Step 1: Add `_seg_case` and `plot_overlay_l4b` to `l4b_figures.py`**

```python
def _seg_case(case: dict, seg: str) -> dict:
    """Per-segment copy of a case dict: fig_id becomes '<Id>_<Partida|Regime>'
    so eng._fig_name produces <fig_prefix>_<Id>_<Partida|Regime>_<Kind> file
    names, matching the existing HIL_L4_<Caso>_<Partida|Regime>_Overlay.pdf
    convention."""
    seg_case = dict(case)
    seg_case["fig_id"] = f"{case['id']}_{seg.capitalize()}"
    return seg_case


def plot_overlay_l4b(t_ms: np.ndarray, data: dict, case: dict, out_dir: Path) -> None:
    """Correntes de fase (a/b/c, via Clarke inversa) + velocidade, FPGA
    (vhdl) vs. PSIM (ref) sobrepostos. Sem painel de fluxo -- PSIM nativo nao
    expoe fluxo do rotor."""
    dut_ia, dut_ib, dut_ic = cc.inverse_clarke(data["vhdl_i_alpha"], data["vhdl_i_beta"])
    ref_ia, ref_ib, ref_ic = cc.inverse_clarke(data["ref_i_alpha"], data["ref_i_beta"])
    t_s = t_ms / 1000.0

    fig, axes = plt.subplots(2, 1, figsize=(7, 6), sharex=True)

    ax = axes[0]
    for dut_y, ref_y, color in zip((dut_ia, dut_ib, dut_ic), (ref_ia, ref_ib, ref_ic), eng.PHASE_COLORS):
        ax.plot(t_s, dut_y, color=color, **eng.VHDL_STYLE)
        ax.plot(t_s, ref_y, color=color, **eng.REF_STYLE)
    ax.set_ylabel("Corrente [A]")
    ax.set_title(f"{case['label']} — correntes de fase")

    ax = axes[1]
    ax.plot(t_s, data["vhdl_speed"], color=eng.COL_VHDL, **eng.VHDL_STYLE)
    ax.plot(t_s, data["ref_speed"], color=eng.COL_C, **eng.REF_STYLE)
    ax.set_ylabel(r"$\omega_{mec}$ [rad/s]")
    ax.set_xlabel("Tempo [s]")

    dut_label, ref_label = eng._labels(case)
    handles = [
        plt.Line2D([], [], color="black", **eng.VHDL_STYLE, label=dut_label),
        plt.Line2D([], [], color="black", **eng.REF_STYLE, label=ref_label),
    ]
    fig.legend(handles=handles, loc="upper right", ncol=2, fontsize=9)
    fig.tight_layout()
    eng.save_fig(fig, out_dir, eng._fig_name(case, "Overlay"))
```

- [ ] **Step 2: Manual run to verify it produces a figure**

```bash
cd verification/cocotb && source .venv/bin/activate
python3 -c "
from pathlib import Path
from l4b_figures import load_l4b_segment, plot_overlay_l4b, _seg_case

campaign = Path('/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-25_campaign_l4_final')
case = {'id': 'A3', 'dir': 'A3_l4', 'label': 'A3 (teste manual)', 'fig_prefix': 'HIL_L4B',
        'labels': {'dut': 'FPGA (real)', 'ref': 'PSIM (independente)'}}
t_ms, data = load_l4b_segment(case, 'regime', campaign)
plot_overlay_l4b(t_ms, data, _seg_case(case, 'regime'), Path('/tmp/l4b_manual_check'))
print('done')
"
ls -la /tmp/l4b_manual_check/
```

- [ ] **Step 3: Visually inspect the output**

Use the Read tool on `/tmp/l4b_manual_check/HIL_L4B_A3_Regime_Overlay.png`.
Confirm: two stacked panels (currents on top with 3 phase colors × solid/dashed pairs, speed on bottom), a legend distinguishing FPGA vs PSIM, no rendering errors, axis labels present, curves visibly overlapping (not flat lines or NaN gaps).

- [ ] **Step 4: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py
git commit -m "feat(l4b): add windowed overlay figure (phase currents + speed)"
```

---

### Task 6: Full-overview figure (`plot_full_overview_l4b`)

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`

**Interfaces:**
- Consumes: `case: dict` with keys `id, dir, label, fig_prefix, psim_csv` (relative path from repo root); `campaign: Path`; `repo_root: Path`.
- Produces: `load_full_fpga_l4b(case, campaign) -> dict` (keys `t, ia, ib, ic, speed`, decimated to ≤6000 points), `load_full_psim_l4b(case, repo_root) -> dict` (same shape), `plot_full_overview_l4b(case, out_dir, campaign, repo_root) -> None` — writes `{out_dir}/{fig_prefix}_{id}_Overview.{pdf,png}`.

No automated test (matplotlib output + real-file I/O, same rationale as Task 5). Verified manually in Step 2.

- [ ] **Step 1: Add the functions to `l4b_figures.py`**

```python
def _decimate(n: int, max_pts: int = 6000) -> slice:
    step = max(1, n // max_pts)
    return slice(None, None, step)


def load_full_fpga_l4b(case: dict, campaign: Path) -> dict:
    """Full FPGA capture (all samples), decimated, phase currents via Clarke
    inversa. Mirrors results_explorer_app.py::_load_full_capture."""
    hilbin_path = campaign / case["dir"] / "raw" / "capture.hilbin"
    _, fpga, _ = H.parse_hilbin(hilbin_path)
    fpga = H._clip_fpga(fpga)
    n = fpga["t"].size
    sl = _decimate(n)
    ia, ib, ic = cc.inverse_clarke(fpga["ia"][sl], fpga["ib"][sl])
    return {
        "t": np.asarray(fpga["t"][sl], dtype=float),
        "ia": np.asarray(ia, dtype=float),
        "ib": np.asarray(ib, dtype=float),
        "ic": np.asarray(ic, dtype=float),
        "speed": np.asarray(fpga["speed"][sl], dtype=float),
    }


def load_full_psim_l4b(case: dict, repo_root: Path) -> dict:
    """Full PSIM CSV export (all samples), decimated, phase currents via
    Clarke inversa. Reuses psim_csv_to_npz.to_psim_channels with the full
    [min,max] time range (i.e. no windowing)."""
    df = psim_mod.load_psim_csv(repo_root / case["psim_csv"])
    channels, _branch = psim_mod.to_psim_channels(df, float(df["Time"].min()), float(df["Time"].max()))
    n = channels["psim_t"].size
    sl = _decimate(n)
    ia, ib, ic = cc.inverse_clarke(channels["psim_ia"][sl], channels["psim_ib"][sl])
    return {
        "t": np.asarray(channels["psim_t"][sl], dtype=float),
        "ia": np.asarray(ia, dtype=float),
        "ib": np.asarray(ib, dtype=float),
        "ic": np.asarray(ic, dtype=float),
        "speed": np.asarray(channels["psim_speed"][sl], dtype=float),
    }


def plot_full_overview_l4b(case: dict, out_dir: Path, campaign: Path, repo_root: Path) -> None:
    """Janela completa: correntes de fase + velocidade, FPGA vs. PSIM, com
    as janelas de partida/regime sombreadas (lidas de metrics.json)."""
    fpga = load_full_fpga_l4b(case, campaign)
    psim = load_full_psim_l4b(case, repo_root)

    mj_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / "metrics.json"
    wins: list[tuple[float, float, str, str]] = []
    if mj_path.is_file():
        mj = json.loads(mj_path.read_text())
        for lbl, col in (("partida", eng.PHASE_COLORS[0]), ("regime", eng.PHASE_COLORS[2])):
            w = mj.get(lbl, {}).get("window_s")
            if w:
                wins.append((w[0], w[1], lbl.capitalize(), col))

    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    ax = axes[0]
    for dut_y, ref_y, color in zip((fpga["ia"], fpga["ib"], fpga["ic"]),
                                     (psim["ia"], psim["ib"], psim["ic"]),
                                     eng.PHASE_COLORS):
        ax.plot(fpga["t"], dut_y, color=color, **eng.VHDL_STYLE)
        ax.plot(psim["t"], ref_y, color=color, **eng.REF_STYLE)
    ax.set_ylabel("Corrente [A]")
    ax.set_title(f"{case['label']} — visão geral")

    ax = axes[1]
    ax.plot(fpga["t"], fpga["speed"], color=eng.COL_VHDL, **eng.VHDL_STYLE)
    ax.plot(psim["t"], psim["speed"], color=eng.COL_C, **eng.REF_STYLE)
    ax.set_ylabel(r"$\omega_{mec}$ [rad/s]")
    ax.set_xlabel("Tempo [s]")

    for a, b, _label, col in wins:
        for panel in axes:
            panel.axvspan(a, b, color=col, alpha=0.13)

    handles = [
        plt.Line2D([], [], color="black", **eng.VHDL_STYLE, label="FPGA (real)"),
        plt.Line2D([], [], color="black", **eng.REF_STYLE, label="PSIM (independente)"),
    ]
    fig.legend(handles=handles, loc="upper right", ncol=2, fontsize=9)
    fig.tight_layout()
    eng.save_fig(fig, out_dir, f"{case['fig_prefix']}_{case['id']}_Overview")
```

- [ ] **Step 2: Manual run and visual check**

```bash
cd verification/cocotb && source .venv/bin/activate
python3 -c "
from pathlib import Path
from l4b_figures import plot_full_overview_l4b

repo_root = Path('/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop')
campaign = repo_root / 'verification/results/2026-07-25_campaign_l4_final'
case = {'id': 'A3', 'dir': 'A3_l4', 'label': 'A3 (teste manual)', 'fig_prefix': 'HIL_L4B',
        'psim_csv': 'extras/induction-motor-model/data/AX/A3_1us.csv'}
plot_full_overview_l4b(case, Path('/tmp/l4b_manual_check'), campaign, repo_root)
print('done')
"
```

Use the Read tool on `/tmp/l4b_manual_check/HIL_L4B_A3_Overview.png`. Confirm:
two panels spanning the full case duration, two shaded regions (partida near
t=0, regime near the end), FPGA and PSIM curves both visible and roughly
tracking each other, no crashes/NaN gaps.

- [ ] **Step 3: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py
git commit -m "feat(l4b): add full-window overview figure"
```

---

### Task 7: CLI wiring — `CASES_L4B`, `generate_case_l4b`, `main`

**Files:**
- Modify: `verification/cocotb/scripts/l4b_figures.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `CASES_L4B: list[dict]`, `generate_case_l4b(case, out_dir, campaign, repo_root) -> dict`, `main(argv=None) -> int`. Running `python3 scripts/l4b_figures.py` with no args must process all 6 cases.

- [ ] **Step 1: Add `CASES_L4B` and the orchestration functions to `l4b_figures.py`**

```python
_L4B_LABELS = {"dut": "FPGA (real)", "ref": "PSIM (independente)"}

CASES_L4B = [
    {"id": "S0", "dir": "S0_l4", "label": "S0 — t$_{acc}$=1 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/S0/S0_1us_trapezoidal.csv", "labels": _L4B_LABELS},
    {"id": "A1", "dir": "A1_l4", "label": "A1 — t$_{acc}$=0,5 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A1_1us.csv", "labels": _L4B_LABELS},
    {"id": "A3", "dir": "A3_l4", "label": "A3 — t$_{acc}$=1 s, carga leve", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A3_1us.csv", "labels": _L4B_LABELS},
    {"id": "A5", "dir": "A5_l4", "label": "A5 — t$_{acc}$=5 s, vazio", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/AX/A5_1us.csv", "labels": _L4B_LABELS},
    {"id": "B1", "dir": "B1_l4", "label": "B1 — degrau 0,25→0,75 T$_n$", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/BX/B1_500ns.csv", "labels": _L4B_LABELS},
    {"id": "B2", "dir": "B2_l4", "label": "B2 — degrau 0,50→1,00 T$_n$", "fig_prefix": "HIL_L4B",
     "psim_csv": "extras/induction-motor-model/data/BX/B2_500ns.csv", "labels": _L4B_LABELS},
]


def generate_case_l4b(case: dict, out_dir: Path, campaign: Path, repo_root: Path) -> dict:
    metrics: dict[str, dict] = {}
    plot_full_overview_l4b(case, out_dir, campaign, repo_root)
    for seg in ("partida", "regime"):
        npz_path = campaign / case["dir"] / "l4_pwm_replay" / "capture" / f"{seg}.npz"
        if not npz_path.is_file():
            continue
        t_ms, data = load_l4b_segment(case, seg, campaign)
        seg_case = _seg_case(case, seg)
        plot_overlay_l4b(t_ms, data, seg_case, out_dir)
        eng.plot_lissajous(t_ms, data, seg_case, out_dir)
        eng.plot_residual(t_ms, data, seg_case, out_dir)
        metrics[seg] = compute_metrics_l4b(data)
    print(f"[ok] {case['id']}: figuras L4-B em {out_dir}")
    return metrics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gera figuras L4-B (FPGA real vs PSIM independente).")
    ap.add_argument("--campaign", type=Path,
                     default=eng.REPO_ROOT / "verification/results/2026-07-25_campaign_l4_final")
    ap.add_argument("--out", type=Path,
                     default=eng.REPO_ROOT / "docs/results-chapter/figures/l4b")
    ap.add_argument("--tables-out", type=Path,
                     default=eng.REPO_ROOT / "docs/results-chapter/tables")
    ap.add_argument("--case", action="append", choices=[c["id"] for c in CASES_L4B],
                     help="ids a gerar (default: todos)")
    args = ap.parse_args(argv)

    selected = [c for c in CASES_L4B if not args.case or c["id"] in args.case]
    all_metrics: dict[str, dict] = {}
    for case in selected:
        all_metrics[case["id"]] = generate_case_l4b(case, args.out, args.campaign, eng.REPO_ROOT)

    args.tables_out.mkdir(parents=True, exist_ok=True)
    (args.tables_out / "l4b_metricas.tex").write_text(render_l4b_table(all_metrics), encoding="utf-8")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "l4b_metrics.json").write_text(json.dumps(all_metrics, indent=2))
    print(f"Tabela gerada em {args.tables_out / 'l4b_metricas.tex'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Remove the placeholder `if __name__ == "__main__": pass` added in Task 1 (this replaces it).

- [ ] **Step 2: Run for all 6 cases**

```bash
cd verification/cocotb && source .venv/bin/activate
python3 scripts/l4b_figures.py
```

Expected: 6 lines of `[ok] <Case>: figuras L4-B em .../docs/results-chapter/figures/l4b`, then `Tabela gerada em .../docs/results-chapter/tables/l4b_metricas.tex`, exit code 0.

- [ ] **Step 3: Verify expected output files exist**

```bash
ls /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/results-chapter/figures/l4b/ | sort
```

Expected: for each of `S0 A1 A3 A5 B1 B2`, one `HIL_L4B_<Case>_Overview.pdf`
(+`.png`), and for each present segment (`Partida`/`Regime`) a
`HIL_L4B_<Case>_<Seg>_Overlay.pdf`, `_Residual.pdf`, and (regime only, per
`generate_case_l4b`'s `if seg == "regime"` — **note:** current code above
calls `plot_lissajous` for every segment, not regime-only; if this diverges
from the intended scope, that's fine, Lissajous is cheap and not
required in the LaTeX text either way, so having it for both segments is not
a bug) `_Lissajous.pdf`. Also confirm
`docs/results-chapter/tables/l4b_metricas.tex` exists and
`cat` it — must contain 6 data rows (`S0 & ...` through `B2 & ...`).

- [ ] **Step 4: Commit**

```bash
git add verification/cocotb/scripts/l4b_figures.py docs/results-chapter/figures/l4b docs/results-chapter/tables/l4b_metricas.tex
git commit -m "feat(l4b): wire CLI, generate figures/table for all 6 cases"
```

---

### Task 8: Copy figures into the LaTeX project

**Files:**
- No new source files — copies generated PDFs into
  `Mestrado_latex/Mestrado/figuras/`.

**Interfaces:** none (manual/scripted file copy, matching how L2/L3/L4
figures are already transferred into the LaTeX project per the existing
workflow).

- [ ] **Step 1: Copy all `HIL_L4B_*.pdf` files**

```bash
cp /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/results-chapter/figures/l4b/HIL_L4B_*.pdf \
   /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/figuras/
```

- [ ] **Step 2: Verify count matches**

```bash
ls /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/results-chapter/figures/l4b/HIL_L4B_*.pdf | wc -l
ls /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/figuras/HIL_L4B_*.pdf | wc -l
```

Both counts must match.

- [ ] **Step 3: Commit (in the Mestrado_latex repo, separate from the HIL repo)**

```bash
cd /home/urielcontardi/Desktop/Projects/Mestrado_latex
git add Mestrado/figuras/HIL_L4B_*.pdf
git commit -m "chore: add L4-B figures (PSIM independent validation)"
```

---

### Task 9: Cap.3 methodology text

**Files:**
- Modify: `Mestrado_latex/Mestrado/chapters/3-MateriaisMetodos.tex:1319-1326` (add table row), and insert a new subsection after line 1326 (`\end{quadro}`).

**Interfaces:** none (LaTeX prose). Depends on Task 7's `docs/results-chapter/tables/l4b_metricas.tex` existing only insofar as the numbers it cites should match — this task does not read that file programmatically, values are transcribed by hand per the existing convention (Section E of the research report: no generated `.tex` fragment in this repo is ever auto-`\input{}`'d).

- [ ] **Step 1: Add the L4-B row to `quad:cadeia-validacao`**

In `Mestrado_latex/Mestrado/chapters/3-MateriaisMetodos.tex`, change (exact current lines 1319-1323):

```latex
        L1 & PSIM $\times$ C & Validar modelo numérico com referência PSIM. \\ \hline
        L2 & C $\times$ VHDL/Vivado & Quantificar efeitos de ponto fixo e discretização. \\ \hline
        L3 & \textit{Top\_HIL} $\times$ C & Verificar cadeia integrada: modulação, Clarke e solver. \\ \hline
        L4 & FPGA/HIL $\times$ offline & Avaliar plataforma em tempo real com telemetria. \\
        \hline
```

to:

```latex
        L1 & PSIM $\times$ C & Validar modelo numérico com referência PSIM. \\ \hline
        L2 & C $\times$ VHDL/Vivado & Quantificar efeitos de ponto fixo e discretização. \\ \hline
        L3 & \textit{Top\_HIL} $\times$ C & Verificar cadeia integrada: modulação, Clarke e solver. \\ \hline
        L4 & FPGA/HIL $\times$ offline & Avaliar plataforma em tempo real com telemetria. \\ \hline
        L4-B & FPGA/HIL $\times$ PSIM (independente) & Corroborar o comportamento observado com uma segunda implementação totalmente independente. \\
        \hline
```

- [ ] **Step 2: Insert the new subsection**, immediately after `\end{quadro}` (current line 1326, before the `A \autoref{fig:CadeiaValidacao}...` paragraph that already follows):

```latex
\subsection{Validação L4-B: Reprodução Independente em PSIM}
\label{subsec:l4b-psim}

Diferentemente de L1 a L4, que isolam uma fonte de erro nova a cada nível, o
L4-B compara a telemetria real da FPGA contra uma reprodução completa e
independente da cadeia V/f, portadora, modulador NPC e motor, feita
inteiramente no PSIM: o bloco de motor de indução nativo da ferramenta,
alimentado por um inversor NPC e um controle escalar V/f também modelados no
PSIM, sem reaproveitar nenhum código C/VHDL do projeto. Por misturar todas as
camadas de uma vez, essa comparação não permite atribuir uma eventual
divergência a uma fonte específica — ao contrário de L1--L4, ela não isola
erro. Seu valor é outro: duas implementações completamente independentes
(o par C/VHDL usado em L2--L4, e o PSIM comercial usado aqui) convergindo
para resultados semelhantes contra a mesma captura real de hardware é
evidência de que o comportamento observado não é um artefato de uma
implementação específica.

A lei de comando V/f usada no PSIM é a mesma lei proporcional pura, sem
reforço de tensão em baixa frequência, já usada no firmware real
(\texttt{src/ps\_app/vf\_ctrl.c}, comentário explícito no código-fonte:
\textit{"V/F ratio — voltage tracks frequency proportionally, no boost"}) —
a lei de controle não é uma variável entre as duas implementações, o que
reforça a comparação. Os parâmetros do motor e a tensão de barramento CC
usados no PSIM são os mesmos da \autoref{tab:motor_params} e das demais
comparações deste trabalho.

A matriz de casos e os resultados quantitativos desta comparação são
apresentados na \autoref{sec:resultados-l4b}.
```

- [ ] **Step 3: Verify the edit visually**

```bash
sed -n '1305,1360p' /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/chapters/3-MateriaisMetodos.tex
```

Confirm the table has 5 data rows now (L1, L2, L3, L4, L4-B), the new
subsection reads coherently, and `\label{subsec:l4b-psim}` /
`\autoref{sec:resultados-l4b}` are present (the latter forward-references a
label Task 10 will create — expected to be unresolved until Task 10 runs;
LaTeX will warn but not error on this, standard multi-pass behavior).

- [ ] **Step 4: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Mestrado_latex
git add Mestrado/chapters/3-MateriaisMetodos.tex
git commit -m "docs: add L4-B definition to Cap.3 (cadeia de validação + subseção)"
```

---

### Task 10: Cap.4 results text

**Files:**
- Modify: `Mestrado_latex/Mestrado/chapters/4-Resultados.tex` — append after the current end of file (line 1065).

**Interfaces:** none (LaTeX prose + figures). Depends on Task 8 (figures
copied into `Mestrado/figuras/`) and the metrics numbers from
`docs/results-chapter/tables/l4b_metricas.tex` (Task 7) — read that file and
transcribe the real numbers into the table below (do not invent numbers;
whatever `l4b_metricas.tex` actually contains after Task 7 runs is what goes
into this table, replacing the illustrative `<...>` placeholders shown here
only as a structural example of where each value goes).

- [ ] **Step 1: Read the real metrics before writing the table**

```bash
cat /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/results-chapter/tables/l4b_metricas.tex
```

Use these exact numbers in Step 2's table — do not use the illustrative
values below verbatim, they are placeholders for structure only.

- [ ] **Step 2: Append the new section to `4-Resultados.tex`**

Append at the end of the file (after current line 1065):

```latex

% ----------------------------------------------------------
\section{Validação L4-B: Reprodução Independente em PSIM}
\label{sec:resultados-l4b}
% ----------------------------------------------------------

Esta seção apresenta a comparação entre a telemetria real da FPGA e a
reprodução completa e independente da cadeia V/f + NPC + motor no PSIM,
definida na \autoref{subsec:l4b-psim}. Diferentemente das seções anteriores
deste capítulo, essa comparação não isola uma fonte de erro específica —
qualquer divergência pode originar-se do modelo do motor, da lei V/f, do
modulador ou do método numérico, todos ao mesmo tempo. As figuras a seguir
não incluem fluxo do rotor: o bloco de motor nativo do PSIM não expõe essa
grandeza.

<REPITA o bloco abaixo para cada um dos 6 casos, substituindo <CASO> por
S0, A1, A3, A5, B1, B2 e <LABEL> pelo texto da coluna "label" de CASES_L4B
em l4b_figures.py (ex.: "S0 — partida a vazio (rampa 1 s)" -- reaproveite a
descrição já usada em resultados_explorer_app.py::_CASE_INFO para manter o
texto consistente com o que já existe em outras partes do projeto)>

\subsection{Caso <CASO>}

\begin{figure}[!htb]
    \caption{\label{fig:l4b-<caso-lower>-overview}Visão geral do caso <CASO>: FPGA \textit{vs.} PSIM independente, com as janelas de partida e regime destacadas.}
    \begin{center}
        \includegraphics[width=\linewidth]{figuras/HIL_L4B_<CASO>_Overview.pdf}
    \end{center}
    \fonte{Elaborado pelo autor (2026).}
\end{figure}

\begin{figure}[!htb]
    \caption{\label{fig:l4b-<caso-lower>-partida}Janela de partida do caso <CASO>: FPGA \textit{vs.} PSIM independente.}
    \begin{center}
        \includegraphics[width=\linewidth]{figuras/HIL_L4B_<CASO>_Partida_Overlay.pdf}
    \end{center}
    \fonte{Elaborado pelo autor (2026).}
\end{figure}

\begin{figure}[!htb]
    \caption{\label{fig:l4b-<caso-lower>-regime}Janela de regime do caso <CASO>: FPGA \textit{vs.} PSIM independente.}
    \begin{center}
        \includegraphics[width=\linewidth]{figuras/HIL_L4B_<CASO>_Regime_Overlay.pdf}
    \end{center}
    \fonte{Elaborado pelo autor (2026).}
\end{figure}

<FIM DO BLOCO REPETIDO>

\subsection{Divergência na Partida do Caso A3}

No caso A3, a janela de partida mostra um mergulho breve de velocidade
(cerca de $-7$~rad/s) presente na captura da FPGA nos primeiros $0{,}15$~s,
ausente na reprodução em PSIM (que permanece próxima de zero até iniciar a
subida). Esse é o único caso da matriz reduzida com divergência qualitativa
visível nesta comparação. A explicação é a mesma limitação já discutida na
\autoref{sec:matriz-cenarios-hil}: o A3 aplica carga desde o início da
rampa, e a lei V/f em malha aberta sem reforço de tensão nem compensação de
escorregamento tem margem de torque reduzida nesse instante. Aqui essa
margem reduzida se manifesta de forma branda — o motor se recupera
rapidamente em vez de perder o sincronismo — mas a sensibilidade a pequenas
diferenças de implementação entre FPGA e PSIM nesse instante crítico é
coerente com o mesmo fenômeno que motivou restringir a matriz original a
cargas leves.

\subsection{Sensibilidade ao Método de Integração (Caso S0)}

Para o caso S0, foi realizado um teste pontual de sanidade numérica: a
simulação foi repetida no PSIM alternando o método de integração entre
Backward Euler e Trapezoidal. Nenhuma diferença foi observada entre os
resultados das duas execuções. Isso não decorre de insensibilidade do modelo
ao método de integração em geral, mas sim de uma característica da
ferramenta: o campo alterado pertence à aba de configuração do motor SPICE
do PSIM, que não tem efeito sobre a simulação nativa efetivamente utilizada
para gerar os resultados desta seção. Este teste não foi repetido de forma
sistemática para os demais cinco casos da matriz.

\begin{table}[htbp]
\centering
\caption{Erro entre FPGA e PSIM independente por caso, janelas de partida e regime: NRMSE das correntes $i_\alpha$/$i_\beta$ e MAE da velocidade mecânica.}
\label{tab:l4b-metricas}
\small
\zebra
<COLE AQUI o conteudo de docs/results-chapter/tables/l4b_metricas.tex lido no Passo 1 -- e o tabular completo, comece a colar a partir de \begin{tabular} ate \end{tabular} inclusive>
\fonte{Elaborado pelo autor (2026).}
\end{table}
```

The `<...>` markers above are structural instructions for this step only —
resolve every one of them (6 case subsections fully written out, real
numbers pasted into the table) before moving to Step 3. No `<...>` marker
may remain in the final file.

- [ ] **Step 3: Verify no template markers remain**

```bash
grep -n "<CASO>\|<LABEL>\|<caso-lower>\|<COLE AQUI\|<REPITA\|<FIM DO BLOCO" \
  /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/chapters/4-Resultados.tex
```

Expected: no output (zero matches). If anything matches, Step 2 is incomplete — go back and resolve it.

- [ ] **Step 4: Verify all referenced figure files actually exist**

```bash
cd /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/figuras
for f in $(grep -o 'HIL_L4B_[A-Za-z0-9_]*\.pdf' ../chapters/4-Resultados.tex); do
  test -f "$f" && echo "ok: $f" || echo "MISSING: $f"
done
```

Expected: `ok:` for every line, zero `MISSING:` lines.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Mestrado_latex
git add Mestrado/chapters/4-Resultados.tex
git commit -m "docs: add L4-B results section (6 cases, A3 divergence, integration-method aside)"
```

---

### Task 11: Structural sanity check

**Files:** none modified — read-only verification of Tasks 9-10's output.

**Interfaces:** none.

- [ ] **Step 1: Check brace/environment balance in both edited chapters**

```bash
cd /home/urielcontardi/Desktop/Projects/Mestrado_latex/Mestrado/chapters
for f in 3-MateriaisMetodos.tex 4-Resultados.tex; do
  echo "=== $f ==="
  for env in figure table quadro tabular center; do
    begins=$(grep -c "\\\\begin{$env}" "$f")
    ends=$(grep -c "\\\\end{$env}" "$f")
    echo "  $env: begin=$begins end=$ends"
    if [ "$begins" != "$ends" ]; then echo "  MISMATCH in $env!"; fi
  done
done
```

Expected: `begin`/`end` counts match for every environment in both files, no `MISMATCH` lines.

- [ ] **Step 2: Check for duplicate labels across both files** (a common LaTeX error source when copy-pasting figure blocks)

```bash
grep -oh '\\label{[^}]*}' 3-MateriaisMetodos.tex 4-Resultados.tex | sort | uniq -d
```

Expected: no output (zero duplicates). If any label appears, fix the duplicate in Task 9 or Task 10's text before proceeding.

- [ ] **Step 3: If a LaTeX build tool is available in this environment, compile; otherwise, note it for the user**

```bash
command -v latexmk >/dev/null 2>&1 && echo "latexmk available" || echo "no local LaTeX toolchain -- ask the user to compile via their usual workflow (e.g. Overleaf sync) before treating this as done"
```

If `latexmk` (or another LaTeX toolchain) is available, compile the full
document per whatever entrypoint the `Mestrado_latex` project already uses
(check `Mestrado_latex/README.md` for the build command) and confirm it
exits 0 with no new `Undefined reference` warnings beyond ones that already
existed before this change. If no toolchain is available in this
environment, explicitly tell the user this step could not be completed
automatically and that they should compile (e.g. via their existing Overleaf
sync workflow) before considering the dissertation text final.

- [ ] **Step 4: Report completion**

Summarize to the user: script + tests committed in the HIL repo, figures +
table generated for all 6 cases, Cap.3 and Cap.4 edits committed in the
Mestrado_latex repo, and whether the compile check in Step 3 could be run.

---

## Self-review notes (already applied above)

- **Spec coverage**: Decision 1 (framing) → Task 9 subsection prose. Decision
  2 (scope: 6 cases, native branch, no B1 episode) → `CASES_L4B` (Task 7) and
  explicit constraint in Global Constraints. Decision 3 (Cap.3) → Task 9.
  Decision 4 (Cap.4: figures, no flux, A3 divergence, integration aside,
  metrics table) → Tasks 6, 10. Decision 5 (pipeline: script, naming, output
  paths) → Tasks 1-8.
- **Two spec discrepancies found during research were corrected in this
  plan**, not silently inherited: `psim_ia`/`psim_ib` are α/β, not raw phase
  currents (fixed in Tasks 5/6 via `inverse_clarke`), and `psim_t` doesn't
  share `fpga_t`'s grid (fixed in Task 1/2 via clipped interpolation). Anyone
  reading only the design spec without this plan would build the wrong
  thing.
