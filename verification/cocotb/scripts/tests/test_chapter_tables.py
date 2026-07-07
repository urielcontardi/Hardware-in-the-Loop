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
