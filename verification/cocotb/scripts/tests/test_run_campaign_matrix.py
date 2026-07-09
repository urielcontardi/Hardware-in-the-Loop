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


from unittest.mock import patch


def test_cocotb_run_passed_true_when_zero_failures(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("some noise\n** TESTS=3 PASS=3 FAIL=0 SKIP=0    123.45   1.00   123.45 **\nmore noise\n")
    assert rcm._cocotb_run_passed(log) is True


def test_cocotb_run_passed_false_when_any_failure(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("** TESTS=1 PASS=0 FAIL=1 SKIP=0    5160310.00   53.23   96942.41 **\n")
    assert rcm._cocotb_run_passed(log) is False


def test_cocotb_run_passed_false_when_no_summary_line(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("Traceback (most recent call last):\n  crashed before summary\n")
    assert rcm._cocotb_run_passed(log) is False


def test_cocotb_run_passed_false_when_log_missing(tmp_path):
    assert rcm._cocotb_run_passed(tmp_path / "does_not_exist.log") is False


def _fake_manifest(ids):
    return {"cases": [{"id": i, "status": "pending", "l2_results": {}, "l3_results": {}} for i in ids]}


def test_run_one_cocotb_writes_run_log_and_returns_ok(tmp_path):
    case_root = tmp_path / "campaign"
    exp = {
        "id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
        "level": "l2", "runner": "cocotb", "test_mode": "vf",
        "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
        "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts",
    }
    config = {"defaults": _defaults(), "case_root": str(case_root)}

    def fake_run_cocotb(exp_, env_, build_dir="sim_build", log_file=None, **kwargs):
        out_dir = case_root / exp_["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(json.dumps({
            "metrics": {"nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
                        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
                        "mae_speed_rad_s": 0.01},
            "duration_s": 0.5, "csv_rows": 100,
        }))
        if log_file is not None:
            log_file.write("** TESTS=1 PASS=1 FAIL=0 SKIP=0    123.45   1.00   123.45 **\n")
        return 0

    with patch.object(rcm, "run_cocotb", side_effect=fake_run_cocotb):
        result = rcm.run_one_cocotb(config, exp, case_root)
    assert result["ok"] is True
    assert result["id"] == "A1_l2"
    log_path = case_root / exp["output_dir"] / "run.log"
    assert log_path.exists()


def test_run_one_cocotb_reports_failure_without_raising(tmp_path):
    case_root = tmp_path / "campaign"
    exp = {
        "id": "A7_l2", "case_id": "A7", "result_key": "vf_2s_realts",
        "level": "l2", "runner": "cocotb", "test_mode": "vf",
        "duration_s": 2.0, "record_interval": 1923, "vf_acc_hz_s": 30.0, "tload_nm": 128.38,
        "output_dir": "A7_tacc2s_load110/l2_vf_2s_realts",
    }
    config = {"defaults": _defaults(), "case_root": str(case_root)}

    with patch.object(rcm, "run_cocotb", return_value=1):
        result = rcm.run_one_cocotb(config, exp, case_root)
    assert result["ok"] is False
    assert result["id"] == "A7_l2"


def test_main_continues_after_one_case_fails(tmp_path, monkeypatch):
    case_root = tmp_path / "campaign"
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.csv"
    config_path = tmp_path / "matrix.json"

    manifest_path.write_text(json.dumps(_fake_manifest(["A1", "A2"])))
    config_path.write_text(json.dumps({
        "case_root": str(case_root),
        "defaults": _defaults(),
        "experiments": [
            {"id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
             "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts"},
            {"id": "A2_l2", "case_id": "A2", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 116.71,
             "output_dir": "A2_tacc0p5s_load100/l2_vf_500ms_realts"},
        ],
    }))

    def fake_run_cocotb(exp_, env_, build_dir="sim_build", log_file=None, **kwargs):
        out_dir = case_root / exp_["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        if exp_["id"] == "A2_l2":
            if log_file is not None:
                log_file.write("** TESTS=1 PASS=0 FAIL=1 SKIP=0    123.45   1.00   123.45 **\n")
            return 1  # simula falha
        (out_dir / "metrics.json").write_text(json.dumps({
            "metrics": {"nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
                        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
                        "mae_speed_rad_s": 0.01},
            "duration_s": 0.5, "csv_rows": 100,
        }))
        if log_file is not None:
            log_file.write("** TESTS=1 PASS=1 FAIL=0 SKIP=0    123.45   1.00   123.45 **\n")
        return 0

    monkeypatch.setattr(rcm, "run_cocotb", fake_run_cocotb)
    monkeypatch.setattr(rcm, "generate_l3_overlay", lambda *a, **k: None)
    monkeypatch.setattr(rcm, "write_readme", lambda *a, **k: None)
    monkeypatch.setattr(rcm, "_regenerate_dashboard", lambda *a, **k: None)

    rc = rcm.main([
        "--config", str(config_path), "--manifest", str(manifest_path),
        "--summary", str(summary_path), "--max-parallel", "2",
    ])

    assert rc == 1  # sinaliza que houve falha, mas nao interrompeu o outro caso
    manifest = json.loads(manifest_path.read_text())
    by_id = {c["id"]: c for c in manifest["cases"]}
    assert "generated" in by_id["A1"]["status"]
    assert by_id["A2"]["status"] == "blocked"


def test_main_skips_cases_already_ok_on_resume(tmp_path, monkeypatch):
    case_root = tmp_path / "campaign"
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.csv"
    config_path = tmp_path / "matrix.json"

    manifest = _fake_manifest(["A1"])
    manifest["cases"][0]["l2_results"] = {"vf_500ms_realts": "A1_tacc0p5s_load000/l2_vf_500ms_realts"}
    manifest["cases"][0]["status"] = "l2_l3_generated"
    manifest_path.write_text(json.dumps(manifest))
    config_path.write_text(json.dumps({
        "case_root": str(case_root),
        "defaults": _defaults(),
        "experiments": [
            {"id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
             "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts"},
        ],
    }))

    calls = []

    def fake_run_cocotb(exp_, env_, build_dir="sim_build", **kwargs):
        calls.append(exp_["id"])
        return 0

    monkeypatch.setattr(rcm, "run_cocotb", fake_run_cocotb)
    monkeypatch.setattr(rcm, "_regenerate_dashboard", lambda *a, **k: None)

    rcm.main(["--config", str(config_path), "--manifest", str(manifest_path),
              "--summary", str(summary_path), "--max-parallel", "1"])

    assert calls == [], "caso ja marcado como generated no manifest nao deveria rodar de novo"


def test_build_l2_env_vf_mode_includes_load_step_when_present(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 1.0, "record_interval": 962,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 29.17840623351415,
        "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert env["HIL_VF_TLOAD_STEP_NM"] == "87.53521870054244"
    assert env["HIL_VF_TLOAD_STEP_TIME_S"] == "0.6"


def test_build_l2_env_vf_mode_omits_load_step_when_absent(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 0.5, "record_interval": 481,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert "HIL_VF_TLOAD_STEP_NM" not in env
    assert "HIL_VF_TLOAD_STEP_TIME_S" not in env
