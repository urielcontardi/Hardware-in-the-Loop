import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l2_figures as eng
import l4_figures as l4


def test_load_segment_maps_fpga_and_c(tmp_path):
    # npz sintetico com o layout real do L4
    seg_dir = tmp_path / "S0_l4/l4_pwm_replay/capture"
    seg_dir.mkdir(parents=True)
    n = 50
    t = np.linspace(0, 0.5, n)
    kw = {k: np.ones(n) for k in
          ("fpga_ia", "cmod_ia", "fpga_ib", "cmod_ib",
           "fpga_flux_a", "cmod_flux_a", "fpga_flux_b", "cmod_flux_b",
           "fpga_speed", "cmod_speed")}
    np.savez(seg_dir / "partida.npz", fpga_t=t, cmod_t=t, **kw)
    case = {"id": "S0", "dir": "S0_l4"}
    t_ms, data = l4.load_segment(case, "partida", tmp_path)
    assert t_ms[-1] == pytest.approx(500.0)  # 0.5 s -> 500 ms
    assert "vhdl_i_alpha" in data and "ref_i_alpha" in data
    assert "vhdl_flux_alpha" in data and "vhdl_speed" in data
    # A telemetria do .hilbin ja entrega i_alpha/i_beta (campos fpga_ia/fpga_ib);
    # o mapeamento e direto, sem Clarke. Com fpga_ia=fpga_ib=1:
    assert data["vhdl_i_alpha"][0] == pytest.approx(1.0)
    assert data["vhdl_i_beta"][0] == pytest.approx(1.0)


def test_generate_l4_end_to_end(tmp_path):
    case = next(c for c in l4.CASES_L4 if c["id"] == "S0")
    npz = l4.CAMPAIGN_L4 / case["dir"] / "l4_pwm_replay/capture/regime.npz"
    if not npz.is_file():
        pytest.skip("dados L4 ausentes")
    metrics = l4.generate_case_l4(case, tmp_path, l4.CAMPAIGN_L4)
    assert (tmp_path / "HIL_L4_S0_Regime_Overlay.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L4_S0_Regime_Lissajous.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L4_S0_Partida_Overlay.pdf").stat().st_size > 0
    # FPGA real vs C: R2 alto em regime
    assert metrics["regime"]["i_alpha"]["r2"] > 0.9


def test_full_overview_end_to_end(tmp_path):
    case = next(c for c in l4.CASES_L4 if c["id"] == "S0")
    hb = l4.CAMPAIGN_L4 / case["dir"] / "raw/capture.hilbin"
    if not hb.is_file():
        pytest.skip("captura .hilbin ausente")
    l4.plot_full_overview(case, tmp_path, l4.CAMPAIGN_L4)
    assert (tmp_path / "HIL_L4_S0_Overview.pdf").stat().st_size > 0
    assert (tmp_path / "HIL_L4_S0_Overview.png").stat().st_size > 0
