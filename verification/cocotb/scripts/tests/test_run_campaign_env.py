"""Testes para as mudancas em run_campaign.py: isolamento de --build-dir,
--test para L2, e a variavel HIL_L3_TLOAD_NM que faltava em build_l3_env."""
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run_campaign as rc


def _base_config():
    return {
        "case_root": "verification/results/fake_campaign/CASE",
        "defaults": {
            "im_clock_frequency": 200_000_000,
            "im_solver_step_cycles": 26,
            "hil_pwm_frequency": 1000,
            "motor": {"rs": 0.4396, "rr": 0.2826, "ls": 0.0031364,
                      "lr": 0.0063264, "lm": 0.1099442, "j": 0.4, "npp": 2.0},
            "vdc": 1240.0,
        },
    }


def test_build_l3_env_includes_tload_nm(tmp_path):
    exp = {"id": "x", "duration_s": 0.5, "tload_nm": 116.7136249340566}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_NM"] == "116.7136249340566"


def test_build_l3_env_tload_nm_defaults_to_zero(tmp_path):
    exp = {"id": "x", "duration_s": 0.5}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_NM"] == "0.0"


def test_run_cocotb_passes_build_dir_and_test_mode():
    exp = {"top": "tim_solver", "test_mode": "vf", "testcase": "test_tim_solver_vf_stimulus"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {}, build_dir="sim_build/A1_l2")
    args = mock_run.call_args[0][0]
    assert "--build-dir" in args
    assert args[args.index("--build-dir") + 1] == "sim_build/A1_l2"
    assert "--test" in args
    assert args[args.index("--test") + 1] == "vf"


def test_run_cocotb_omits_test_flag_when_no_test_mode():
    exp = {"top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {}, build_dir="sim_build/A1_l3")
    args = mock_run.call_args[0][0]
    assert "--test" not in args


def test_run_cocotb_defaults_build_dir_to_sim_build():
    exp = {"top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {})
    args = mock_run.call_args[0][0]
    assert args[args.index("--build-dir") + 1] == "sim_build"


def test_run_cocotb_redirects_to_log_file_when_given():
    exp = {"top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3"}
    fake_log = io.StringIO()
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {}, build_dir="sim_build/x", log_file=fake_log)
    _, kwargs = mock_run.call_args
    assert kwargs.get("stdout") is fake_log
    assert kwargs.get("stderr") == rc.subprocess.STDOUT


def test_build_l3_env_includes_load_step_when_present(tmp_path):
    exp = {
        "id": "x", "duration_s": 1.0, "tload_nm": 29.17840623351415,
        "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
    }
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_STEP_NM"] == "87.53521870054244"
    assert env["HIL_L3_TLOAD_STEP_TIME_S"] == "0.6"


def test_build_l3_env_omits_load_step_when_absent(tmp_path):
    exp = {"id": "x", "duration_s": 0.5, "tload_nm": 0.0}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert "HIL_L3_TLOAD_STEP_NM" not in env
    assert "HIL_L3_TLOAD_STEP_TIME_S" not in env
