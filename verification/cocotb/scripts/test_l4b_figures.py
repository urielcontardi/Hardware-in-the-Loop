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
