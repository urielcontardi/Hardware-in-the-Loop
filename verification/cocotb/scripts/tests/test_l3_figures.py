import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l2_figures as eng


SIGS = ["i_alpha", "i_beta", "flux_alpha", "flux_beta", "speed"]


def _write_l3_csv(path: Path, time_col: str, ref_prefix: str, extra=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [time_col] + [f"vhdl_{s}" for s in SIGS] + [f"{ref_prefix}_{s}" for s in SIGS] + list(extra)
    rows = []
    for i in range(4):
        vals = [i * 1e-3] + [float(i)] * len(SIGS) + [float(i) * 1.01] * len(SIGS) + [6] * len(extra)
        rows.append(",".join(str(v) for v in vals))
    path.write_text(",".join(header) + "\n" + "\n".join(rows) + "\n")


def test_load_case_ts_time_and_c_prefix(tmp_path):
    """load_case aceita t_s e prefixo c_, canonicalizando p/ ref_ e t_ms."""
    _write_l3_csv(tmp_path / "d/fullstack_vs_top.csv", "t_s", "c", extra=("va", "vb", "vc"))
    case = {"dir": "d", "csv": "fullstack_vs_top.csv",
            "time_col": "t_s", "ref_prefix": "c", "extra_cols": ["va", "vb", "vc"]}
    t_ms, data = eng.load_case(case, tmp_path)
    # t_s -> ms : 3e-3 s == 3.0 ms na ultima amostra
    assert t_ms[-1] == pytest.approx(3.0)
    # colunas de referencia canonicalizadas para ref_*
    assert "ref_i_alpha" in data and "c_i_alpha" not in data
    assert data["ref_i_alpha"][1] == pytest.approx(1.01)
    assert data["vhdl_i_alpha"][1] == pytest.approx(1.0)
    # colunas extras preservadas
    assert data["va"][0] == pytest.approx(6.0)


def test_load_case_defaults_l2_unchanged(tmp_path):
    """Sem time_col/ref_prefix: comportamento L2 (t_us, ref_) preservado."""
    _write_l3_csv(tmp_path / "d/x.csv", "t_us", "ref")
    case = {"dir": "d", "csv": "x.csv"}
    t_ms, data = eng.load_case(case, tmp_path)
    assert t_ms[-1] == pytest.approx(3e-6)  # t_us=3e-3 -> 3e-6 ms
    assert "ref_i_alpha" in data


def test_labels_default_and_custom():
    assert eng._labels({}) == ("VHDL", "C")
    assert eng._labels({"labels": {"dut": "Top_HIL", "ref": "C indep."}}) == ("Top_HIL", "C indep.")


def test_plot_pwm_stimulus_creates_files(tmp_path):
    n = 400
    t_ms = np.linspace(0, 20, n)  # 0..20 ms
    ph = 2 * np.pi * 60 * (t_ms * 1e-3)
    # onda NPC multinivel sintetica (degraus)
    va = 620 * np.sign(np.sin(ph))
    vb = 620 * np.sign(np.sin(ph - 2 * np.pi / 3))
    vc = 620 * np.sign(np.sin(ph + 2 * np.pi / 3))
    ia = 20 * np.sin(ph)
    ib = 20 * np.sin(ph - 2 * np.pi / 3)
    data = {"va": va.tolist(), "vb": vb.tolist(), "vc": vc.tolist(),
            "vhdl_i_alpha": ia.tolist(), "vhdl_i_beta": ((ia + 2 * ib) / np.sqrt(3)).tolist()}
    case = {"id": "vf2s", "label": "V/f 2 s", "tipo": "vf", "fig_prefix": "HIL_L3",
            "labels": {"dut": "Top_HIL", "ref": "C"}, "pwm_zoom_ms": (5.0, 15.0)}
    eng.plot_pwm_stimulus(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L3_VF2s_PWMStimulus.pdf").stat().st_size > 0


def test_phase_analysis_recovers_known_offset():
    fs = 4000.0
    t = np.arange(0.0, 0.5, 1.0 / fs)
    a = np.sin(2 * np.pi * 60 * t)
    b = np.sin(2 * np.pi * 60 * t - np.pi / 2)  # vetor girante
    k = 5  # ref adiantada de k amostras
    ra, rb = np.roll(a, k), np.roll(b, k)
    data = {"vhdl_i_alpha": a, "vhdl_i_beta": b, "ref_i_alpha": ra, "ref_i_beta": rb}
    pa = eng.phase_analysis(t * 1000.0, data, window_s=(0.1, 0.5))
    expected = 360.0 * 60 * k / fs
    assert abs(abs(pa["phase_deg"]) - expected) < 2.0
    assert pa["nrmse_aligned"] < pa["nrmse_raw"]


def test_phase_drift_zero_when_identical():
    t = np.linspace(0, 0.1, 400)
    a = np.sin(2 * np.pi * 60 * t)
    b = np.sin(2 * np.pi * 60 * t - np.pi / 2)
    data = {"vhdl_i_alpha": a, "vhdl_i_beta": b, "ref_i_alpha": a, "ref_i_beta": b}
    d = eng.phase_drift_deg(data)
    assert np.max(np.abs(d)) < 1e-6


import l3_figures as l3


def test_l3_manifest_has_pwm_replay_and_fullstack():
    ids = {c["id"] for c in l3.CASES_L3}
    assert any("pwmreplay" in i for i in ids)
    assert any("fullstack" in i for i in ids)
    # todos L3 usam t_s e prefixo de figura HIL_L3
    for c in l3.CASES_L3:
        assert c["time_col"] == "t_s"
        assert c["fig_prefix"] == "HIL_L3"


def test_generate_pwm_replay_end_to_end(tmp_path):
    case = next(c for c in l3.CASES_L3 if c["id"] == "pwmreplay_vf2s")
    if not (l3.CAMPAIGN_DIR / case["dir"] / case["csv"]).is_file():
        pytest.skip("dados L3 da campanha_03 ausentes")
    metrics = eng.generate_case(case, tmp_path, l3.CAMPAIGN_DIR)
    assert (tmp_path / "HIL_L3_PWMreplay_VF2s_Overlay.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L3_PWMreplay_VF2s_PWMStimulus.pdf").stat().st_size > 0
    assert 0.0 < metrics["i_alpha"]["nrmse"] < 0.1


def test_generate_fullstack_end_to_end(tmp_path):
    case = next(c for c in l3.CASES_L3 if c["id"] == "fullstack_vf2s")
    if not (l3.CAMPAIGN_DIR / case["dir"] / case["csv"]).is_file():
        pytest.skip("dados L3 da campanha_03 ausentes")
    metrics = eng.generate_case(case, tmp_path, l3.CAMPAIGN_DIR)
    assert (tmp_path / "HIL_L3_Fullstack_VF2s_Overlay.pdf").stat().st_size > 0
    assert metrics["i_alpha"]["r2"] > 0.9


def test_phase_drift_comparison_figure_and_numbers(tmp_path):
    replay = next(c for c in l3.CASES_L3 if c["id"] == "pwmreplay_vf2s")
    full = next(c for c in l3.CASES_L3 if c["id"] == "fullstack_vf2s")
    if not (l3.CAMPAIGN_DIR / full["dir"] / full["csv"]).is_file():
        pytest.skip("dados L3 da campanha_03 ausentes")
    info = l3.plot_phase_drift_comparison(replay, full, tmp_path, l3.CAMPAIGN_DIR)
    assert (tmp_path / "HIL_L3_PhaseDrift.pdf").stat().st_size > 0
    # replay ~0°, full-stack ~20° no fim
    assert abs(info["replay_end_deg"]) < 3.0
    assert info["fullstack_end_deg"] > 15.0
