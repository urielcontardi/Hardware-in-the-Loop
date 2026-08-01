from pathlib import Path

import numpy as np

from l4b_figures import (
    _overlap_mask_and_grid,
    compute_metrics_l4b,
    load_l4b_segment,
    render_l4b_table,
)


def test_overlap_mask_and_grid_clips_to_shorter_series():
    fpga_t = np.linspace(0.0, 1.0, 11)   # 0.0, 0.1, ..., 1.0
    psim_t = np.linspace(0.0, 0.6, 601)  # 0.0 .. 0.6, stops early (like regime window)
    mask, t_common = _overlap_mask_and_grid(fpga_t, psim_t)
    assert t_common.max() <= 0.6 + 1e-9
    assert t_common.min() >= 0.0 - 1e-9
    assert mask.sum() == t_common.size
    assert np.array_equal(fpga_t[mask], t_common)


def test_load_l4b_segment_a3_regime_has_expected_shape_and_units():
    campaign = Path("/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-25_campaign_l4_final")
    case = {"id": "A3", "dir": "A3_l4"}
    t_ms, data = load_l4b_segment(case, "regime", campaign)
    assert t_ms.max() > t_ms.min()
    assert t_ms.max() <= 3000.0 + 1.0  # PSIM regime data stops at ~3.0s -> 3000ms
    for key in ("vhdl_i_alpha", "vhdl_i_beta", "vhdl_speed", "ref_i_alpha", "ref_i_beta", "ref_speed"):
        assert data[key].shape == t_ms.shape
    # sanity: speeds should be in the same ballpark (both near sync ~187 rad/s in regime)
    assert abs(float(np.mean(data["vhdl_speed"])) - float(np.mean(data["ref_speed"]))) < 5.0


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
