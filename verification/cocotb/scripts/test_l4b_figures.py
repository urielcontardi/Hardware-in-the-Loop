from pathlib import Path

import numpy as np

from l4b_figures import _overlap_mask_and_grid, load_l4b_segment


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
