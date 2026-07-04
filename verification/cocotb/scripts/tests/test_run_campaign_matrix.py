"""Testes das funcoes puras do orquestrador: env L2, manifest, summary.csv.
Nao invoca nenhum simulador nem gcc — subprocess.run e sempre mockado."""
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run_campaign_matrix as rcm


def _defaults():
    return {
        "im_clock_frequency": 200_000_000,
        "im_solver_step_cycles": 26,
        "motor": {"rs": 0.4396, "rr": 0.2826, "ls": 0.0031364,
                  "lr": 0.0063264, "lm": 0.1099442, "j": 0.4, "npp": 2.0},
        "vdc": 1240.0,
        "v_peak": 620.0,
        "initial_theta_rad": math.pi / 4,
        "warmup_steps": 400,
    }


def test_build_l2_env_vf_mode(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 0.5, "record_interval": 481,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 116.7136249340566,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert env["IM_RS"] == "0.4396"
    assert env["IM_J"] == "0.4"
    assert env["HIL_VF_DURATION_S"] == "0.5"
    assert env["HIL_VF_ACC_RAMP_HZ_S"] == "120.0"
    assert env["HIL_VF_TLOAD_NM"] == "116.7136249340566"
    assert env["HIL_VF_CSV"] == str((tmp_path / "vf_vhdl_vs_c.csv").resolve())
    assert env["HIL_VF_METRICS"] == str((tmp_path / "metrics.json").resolve())


def test_build_l2_env_sine_mode_computes_steps_from_duration(tmp_path):
    config = {"defaults": _defaults()}
    exp = {"test_mode": "sine", "duration_s": 0.20, "sine_freq_hz": 60.0, "tload_nm": 0.0}
    env = rcm.build_l2_env(config, exp, tmp_path)
    # Ts = 26/200e6 = 1.3e-7 s; steps = round(0.20 / 1.3e-7) = 1538462
    assert env["HIL_SINE_STEPS"] == "1538462"
    assert env["HIL_SINE_FREQ_HZ"] == "60.0"
    assert env["HIL_SINE_CSV"] == str((tmp_path / "sine_vhdl_vs_c.csv").resolve())


def test_build_l2_env_rejects_unknown_test_mode(tmp_path):
    config = {"defaults": _defaults()}
    exp = {"test_mode": "bogus", "duration_s": 0.1}
    try:
        rcm.build_l2_env(config, exp, tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_append_summary_row_creates_header(tmp_path):
    csv_path = tmp_path / "summary.csv"
    rcm.append_summary_row(csv_path, {
        "case": "A1", "level": "L2", "status": "generated",
        "path": "A1_tacc0p5s_load000/l2_vf_500ms_realts",
        "duration_s": 0.5, "t_acc_s": 0.5, "tload_nm": 0.0, "csv_rows": 9615,
        "nrmse_i_alpha": 0.0462, "nrmse_i_beta": 0.0471,
        "mae_flux_alpha_wb": 0.0090, "mae_flux_beta_wb": 0.0101,
        "mae_speed_rad_s": 0.369,
        "overlay": "A1_tacc0p5s_load000/l2_vf_500ms_realts/overlay.html",
        "note": "formal Grupo A; sem carga",
    })
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["case"] == "A1"
    assert rows[0]["level"] == "L2"


def test_append_summary_row_appends_without_duplicating_header(tmp_path):
    csv_path = tmp_path / "summary.csv"
    row = {
        "case": "A1", "level": "L2", "status": "generated", "path": "p",
        "duration_s": 0.5, "t_acc_s": 0.5, "tload_nm": 0.0, "csv_rows": 1,
        "nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
        "mae_speed_rad_s": 0.01, "overlay": "o", "note": "n",
    }
    rcm.append_summary_row(csv_path, row)
    rcm.append_summary_row(csv_path, {**row, "case": "A2"})
    with csv_path.open() as f:
        lines = f.readlines()
    assert lines[0].startswith("case,level,status")
    assert len(lines) == 3


def test_update_manifest_case_marks_partial_then_full():
    manifest = {"cases": [{"id": "A1", "status": "pending", "l2_results": {}, "l3_results": {}}]}
    rcm.update_manifest_case(manifest, "A1", "l2", "vf_500ms_realts",
                              "A1_tacc0p5s_load000/l2_vf_500ms_realts", ok=True)
    case = manifest["cases"][0]
    assert case["l2_results"]["vf_500ms_realts"] == "A1_tacc0p5s_load000/l2_vf_500ms_realts"
    assert "generated" in case["status"]

    rcm.update_manifest_case(manifest, "A1", "l3", "pwm_replay_vf_500ms",
                              "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms", ok=True)
    assert case["l3_results"]["pwm_replay_vf_500ms"] == "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms"
    assert case["status"] == "l2_l3_generated"


def test_update_manifest_case_marks_blocked_on_failure():
    manifest = {"cases": [{"id": "A2", "status": "pending", "l2_results": {}, "l3_results": {}}]}
    rcm.update_manifest_case(manifest, "A2", "l2", "vf_500ms_realts",
                              "A2_tacc0p5s_load100/l2_vf_500ms_realts", ok=False)
    assert manifest["cases"][0]["status"] == "blocked"
