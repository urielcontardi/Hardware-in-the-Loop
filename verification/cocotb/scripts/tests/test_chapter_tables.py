import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc
import chapter_tables as ct


def _case(case_id, t_acc, load, l2=None, l3=None):
    return cc.CaseMetrics(case_id=case_id, t_acc_s=t_acc, load_tn=load,
                           l2=l2, l3=l3, l2_csv=None, l3_csv=None)


def test_render_parametros_grupo_a_places_cases_in_matrix():
    cases = [_case("A1", 0.5, 0.0), _case("A2", 0.5, 1.0)]

    tex = ct.render_parametros_grupo_a(cases)

    row_05 = next(line for line in tex.splitlines() if line.startswith("0.5~s"))
    cells = [c.strip() for c in row_05.split("&")]
    assert cells[1] == "A1"   # carga = 0.0
    assert cells[3] == "A2"   # carga = 1.0


def test_render_metricas_grupo_a_uses_dashes_for_missing_level():
    metrics = {
        "nrmse_i_alpha": 0.03, "nrmse_i_beta": 0.03,
        "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.001,
        "mae_speed_rad_s": 0.3,
    }
    cases = [_case("A1", 0.5, 0.0, l2=metrics, l3=None)]

    tex = ct.render_metricas_grupo_a(cases)

    row = next(line for line in tex.splitlines() if line.startswith("A1"))
    cells = [c.strip() for c in row.rstrip("\\").split("&")]
    assert cells[1] == "3.00\\%"  # L2 nrmse_i_alpha
    assert cells[-1] == "--"      # L3 mae_speed_rad_s, missing


def _case_b(case_id, pre, post, l2=None, l3=None, l2_transient=None, l3_transient=None,
            l2_run_log=None, l3_run_log=None):
    return cc.CaseMetrics(case_id=case_id, t_acc_s=None, load_tn=None,
                           l2=l2, l3=l3, l2_csv=None, l3_csv=None, group="b",
                           tload_pre_nm=pre, tload_post_nm=post, t_step_s=0.6,
                           l2_transient=l2_transient, l3_transient=l3_transient,
                           l2_run_log=l2_run_log, l3_run_log=l3_run_log)


def test_render_parametros_grupo_b_shows_direction():
    cases = [_case_b("B1", 25.0, 75.0), _case_b("B3", 75.0, 25.0)]

    tex = ct.render_parametros_grupo_b(cases, t_n=100.0)

    row_b1 = next(l for l in tex.splitlines() if l.startswith("B1"))
    assert "subida" in row_b1
    row_b3 = next(l for l in tex.splitlines() if l.startswith("B3"))
    assert "descida" in row_b3


def test_render_parametros_grupo_b_dashes_without_t_n():
    cases = [_case_b("B1", 25.0, 75.0)]

    tex = ct.render_parametros_grupo_b(cases, t_n=None)

    row = next(l for l in tex.splitlines() if l.startswith("B1"))
    assert "--" in row


def test_render_metricas_grupo_b_uses_dashes_for_missing_level():
    metrics = {
        "nrmse_i_alpha": 0.04, "nrmse_i_beta": 0.04,
        "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.001,
        "mae_speed_rad_s": 0.3,
    }
    cases = [_case_b("B1", 25.0, 75.0, l2=metrics, l3=None)]

    tex = ct.render_metricas_grupo_b(cases)

    row = next(l for l in tex.splitlines() if l.startswith("B1"))
    cells = [c.strip() for c in row.rstrip("\\").split("&")]
    assert cells[1] == "4.00\\%"
    assert cells[-1] == "--"


def test_render_transiente_grupo_b_reports_vhdl_and_c_and_skips_missing_level():
    transient = {
        "vhdl": {"speed_peak_deviation_rad_s": 0.7186, "recovery_time_s": 3.788e-05},
        "c": {"speed_peak_deviation_rad_s": 0.8181, "recovery_time_s": 3.788e-05},
    }
    cases = [_case_b("B1", 25.0, 75.0, l2_transient=transient, l3_transient=None)]

    tex = ct.render_transiente_grupo_b(cases)
    lines = tex.splitlines()

    row = next(l for l in lines if l.startswith("B1 (L2)"))
    assert "0.719" in row  # VHDL peak deviation, 3 sig figs
    assert not any(l.startswith("B1 (L3)") for l in lines)


def test_render_tempo_simulacao_computes_deceleration_factor(tmp_path):
    run_log = tmp_path / "run.log"
    run_log.write_text(
        "** TESTS=1 PASS=1 FAIL=0 SKIP=0                           "
        "500000000.00       2500.00      50000.00  **\n"
    )
    case = cc.CaseMetrics(case_id="A1", t_acc_s=0.5, load_tn=0.0, l2=None, l3=None,
                           l2_csv=None, l3_csv=None, l2_run_log=run_log, l3_run_log=None)

    tex = ct.render_tempo_simulacao([case])

    row = next(l for l in tex.splitlines() if l.startswith("A1 (L2)"))
    cells = [c.strip() for c in row.rstrip("\\").split("&")]
    assert cells[1] == "0.500"
    assert cells[2] == "2500.0"
    assert cells[3] == "5000\\times"


def test_render_tempo_simulacao_dashes_without_run_log():
    case = cc.CaseMetrics(case_id="A2", t_acc_s=0.5, load_tn=1.0, l2=None, l3=None,
                           l2_csv=None, l3_csv=None, l2_run_log=None, l3_run_log=None)

    tex = ct.render_tempo_simulacao([case])

    assert not any(l.startswith("A2 (L2)") for l in tex.splitlines())
