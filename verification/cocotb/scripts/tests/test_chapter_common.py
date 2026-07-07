import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc


def _write_metrics(path: Path, nrmse_a: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "metrics": {
            "nrmse_i_alpha": nrmse_a,
            "nrmse_i_beta": nrmse_a * 0.9,
            "mae_flux_alpha_wb": 0.001,
            "mae_flux_beta_wb": 0.0011,
            "mae_speed_rad_s": 0.3,
        }
    }))


def _manifest() -> dict:
    return {
        "cases": [
            {"id": "A1", "dir": "A1_tacc0p5s_load000", "t_acc_s": 0.5, "load_tn": 0.0,
             "l2_results": {}, "l3_results": {}},
            {"id": "A2", "dir": "A2_tacc0p5s_load100", "t_acc_s": 0.5, "load_tn": 1.0,
             "l2_results": {}, "l3_results": {}},
        ]
    }


def test_load_grupo_a_finds_metrics_ignoring_manifest_results_dict(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A2_tacc0p5s_load100/l2_vf_500ms_realts/metrics.json", 0.02)
    # A2 has no l3 dir at all -- simulates L2 done, L3 still pending

    cases = cc.load_grupo_a(tmp_path)

    assert [c.case_id for c in cases] == ["A1", "A2"]
    a1, a2 = cases
    assert a1.l2["nrmse_i_alpha"] == 0.03
    assert a1.l3["nrmse_i_alpha"] == 0.031
    assert a2.l2["nrmse_i_alpha"] == 0.02
    assert a2.l3 is None


def test_write_gaps_report_lists_missing_levels(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A2_tacc0p5s_load100/l2_vf_500ms_realts/metrics.json", 0.02)

    cases = cc.load_grupo_a(tmp_path)
    out_path = tmp_path / "gaps.md"
    cc.write_gaps_report(cases, out_path)

    text = out_path.read_text()
    assert "A2: L3 ausente (metrics.json não encontrado)" in text
    assert "A1: L2 ausente" not in text
    assert "A1: L3 ausente" not in text


def test_load_csv_columns_parses_floats(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("t_us,vhdl_i_alpha\n0,0.1\n10,0.2\n")

    data = cc.load_csv_columns(csv_path, ["t_us", "vhdl_i_alpha"])

    assert data["t_us"] == [0.0, 10.0]
    assert data["vhdl_i_alpha"] == [0.1, 0.2]
