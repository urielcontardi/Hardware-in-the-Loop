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
            {"id": "A3", "dir": "A3_tacc1s_load050", "t_acc_s": 1.0, "load_tn": 0.5,
             "l2_results": {}, "l3_results": {}},
        ]
    }


def test_load_grupo_a_finds_metrics_ignoring_manifest_results_dict(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A3_tacc1s_load050/l2_vf_1s_realts/metrics.json", 0.02)
    # A3 has no l3 dir at all -- simulates L2 done, L3 still pending

    cases = cc.load_grupo_a(tmp_path)

    assert [c.case_id for c in cases] == ["A1", "A3"]
    a1, a3 = cases
    assert a1.l2["nrmse_i_alpha"] == 0.03
    assert a1.l3["nrmse_i_alpha"] == 0.031
    assert a3.l2["nrmse_i_alpha"] == 0.02
    assert a3.l3 is None


def test_write_gaps_report_lists_missing_levels(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_metrics(tmp_path / "A3_tacc1s_load050/l2_vf_1s_realts/metrics.json", 0.02)

    cases = cc.load_grupo_a(tmp_path)
    out_path = tmp_path / "gaps.md"
    cc.write_gaps_report(cases, out_path)

    text = out_path.read_text()
    assert "A3: L3 ausente (metrics.json não encontrado)" in text
    assert "A1: L2 ausente" not in text
    assert "A1: L3 ausente" not in text


def test_load_csv_columns_parses_floats(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("t_us,vhdl_i_alpha\n0,0.1\n10,0.2\n")

    data = cc.load_csv_columns(csv_path, ["t_us", "vhdl_i_alpha"])

    assert data["t_us"] == [0.0, 10.0]
    assert data["vhdl_i_alpha"] == [0.1, 0.2]


import pytest


def _write_metrics_with_transient(path: Path, nrmse_a: float,
                                   peak_dev_vhdl: float, peak_dev_c: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "metrics": {
            "nrmse_i_alpha": nrmse_a, "nrmse_i_beta": nrmse_a * 0.9,
            "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.0011,
            "mae_speed_rad_s": 0.3,
        },
        "transient": {
            "vhdl": {"speed_peak_deviation_rad_s": peak_dev_vhdl, "recovery_time_s": 3.788e-05},
            "c": {"speed_peak_deviation_rad_s": peak_dev_c, "recovery_time_s": 3.788e-05},
        },
    }))


def _manifest_b() -> dict:
    return {
        "defaults": {"torque_nominal_nm": 100.0},
        "cases": [
            {"id": "B1", "dir": "B1_step025_to075", "group": "perturbacao_carga",
             "tload_pre_nm": 25.0, "tload_post_nm": 75.0, "t_step_s": 0.6},
            {"id": "B2", "dir": "B2_step050_to100", "group": "perturbacao_carga",
             "tload_pre_nm": 50.0, "tload_post_nm": 100.0, "t_step_s": 0.6},
        ],
    }


def test_load_grupo_b_resolves_step_pattern_dirs(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest_b()))
    _write_metrics(tmp_path / "B1_step025_to075/l2_step_1s/metrics.json", 0.04)
    _write_metrics(tmp_path / "B1_step025_to075/l3_top_pwm_replay_step_1s/metrics.json", 0.041)
    # B2 has no l3 dir at all -- simulates L2 done, L3 still pending

    cases = cc.load_grupo_b(tmp_path)

    assert [c.case_id for c in cases] == ["B1", "B2"]
    b1, b2 = cases
    assert b1.group == "b"
    assert b1.tload_pre_nm == 25.0
    assert b1.tload_post_nm == 75.0
    assert b1.l2["nrmse_i_alpha"] == 0.04
    assert b1.l3["nrmse_i_alpha"] == 0.041
    assert b2.l3 is None


def test_load_grupo_b_reads_transient_block(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest_b()))
    _write_metrics_with_transient(
        tmp_path / "B1_step025_to075/l2_step_1s/metrics.json", 0.04, 0.7186, 0.8181)

    cases = cc.load_grupo_b(tmp_path)

    assert cases[0].l2_transient["vhdl"]["speed_peak_deviation_rad_s"] == 0.7186
    assert cases[0].l2_transient["c"]["speed_peak_deviation_rad_s"] == 0.8181
    assert cases[1].l2_transient is None


def test_load_defaults_reads_torque_nominal(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest_b()))

    defaults = cc.load_defaults(tmp_path)

    assert defaults["torque_nominal_nm"] == 100.0


def test_load_defaults_returns_empty_dict_without_defaults_key(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"cases": []}))

    assert cc.load_defaults(tmp_path) == {}


REAL_TESTS_LINE = (
    "** TESTS=1 PASS=1 FAIL=0 SKIP=0                           "
    "1001001120.00       12037.31      83158.22  **"
)


def test_parse_run_log_timing_extracts_sim_and_wall_time(tmp_path):
    run_log = tmp_path / "run.log"
    run_log.write_text("some preamble\n" + REAL_TESTS_LINE + "\ntrailer\n")

    result = cc.parse_run_log_timing(run_log)

    assert result is not None
    sim_time_s, wall_time_s = result
    assert sim_time_s == pytest.approx(1.00100112)
    assert wall_time_s == pytest.approx(12037.31)


def test_parse_run_log_timing_returns_none_without_tests_line(tmp_path):
    run_log = tmp_path / "run.log"
    run_log.write_text("no summary here\njust some other text\n")

    assert cc.parse_run_log_timing(run_log) is None


def test_parse_run_log_timing_returns_none_for_missing_file(tmp_path):
    assert cc.parse_run_log_timing(tmp_path / "does_not_exist.log") is None


def test_inverse_clarke_balanced_sums_to_zero():
    import chapter_common as cc
    ia, ib, ic = cc.inverse_clarke([1.0, 2.0], [0.0, 0.5])
    # sistema equilibrado: ia+ib+ic == 0 em cada amostra
    for a, b, c in zip(ia, ib, ic):
        assert abs(a + b + c) < 1e-12
    # alpha mapeia direto para ia
    assert ia == [1.0, 2.0]
