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


def test_plot_overlay_creates_files(tmp_path):
    import numpy as np
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
    t_ms = np.asarray(t) * 1e-3
    case = {"id": "smoke", "label": "Smoke", "tipo": "vf", "zoom": []}
    l2.plot_overlay(t_ms, data, case, tmp_path)
    assert (tmp_path / "HIL_L2_Smoke_Overlay.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L2_Smoke_Overlay.png").stat().st_size > 0
