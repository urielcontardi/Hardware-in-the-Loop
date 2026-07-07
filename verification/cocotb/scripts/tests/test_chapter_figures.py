import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chapter_common as cc
import chapter_figures as cf


def _write_metrics(path: Path, nrmse_a: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metrics": {
        "nrmse_i_alpha": nrmse_a, "nrmse_i_beta": nrmse_a * 0.9,
        "mae_flux_alpha_wb": 0.001, "mae_flux_beta_wb": 0.0011,
        "mae_speed_rad_s": 0.3,
    }}))


def _write_csv(path: Path, time_col: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [time_col, "vhdl_i_alpha", "ref_i_alpha", "vhdl_i_beta", "ref_i_beta",
              "vhdl_speed", "ref_speed"]
    rows = [
        [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [1, 0.5, 0.4, 0.3, 0.25, 1.0, 0.9],
        [2, 1.0, 0.9, 0.6, 0.55, 2.0, 1.9],
    ]
    lines = [",".join(header)] + [",".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")


def _build_campaign(tmp_path: Path) -> Path:
    manifest = {"cases": [
        {"id": "A1", "dir": "A1_tacc0p5s_load000", "t_acc_s": 0.5, "load_tn": 0.0},
        {"id": "A5", "dir": "A5_tacc5s_load000", "t_acc_s": 5.0, "load_tn": 0.0},
    ]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l2_vf_500ms_realts/metrics.json", 0.03)
    _write_metrics(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/metrics.json", 0.031)
    _write_csv(tmp_path / "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms/top_pwm_replay_vs_c.csv", "t_s")
    _write_metrics(tmp_path / "A5_tacc5s_load000/l2_vf_5s_realts/metrics.json", 0.04)
    return tmp_path


def test_plot_forma_onda_writes_nonempty_pdf(tmp_path):
    campaign_dir = _build_campaign(tmp_path)
    cases = cc.load_grupo_a(campaign_dir)
    a1 = next(c for c in cases if c.case_id == "A1")
    out_path = tmp_path / "out" / "forma_onda_A1.pdf"

    ok = cf.plot_forma_onda(a1, out_path)

    assert ok is True
    assert out_path.stat().st_size > 0


def test_plot_forma_onda_returns_false_without_csv():
    case = cc.CaseMetrics(case_id="X", t_acc_s=1.0, load_tn=0.0,
                           l2=None, l3=None, l2_csv=None, l3_csv=None)

    ok = cf.plot_forma_onda(case, Path("/tmp/should-not-be-created.pdf"))

    assert ok is False


def test_plot_resumo_charts_run_with_partial_data(tmp_path):
    campaign_dir = _build_campaign(tmp_path)
    cases = cc.load_grupo_a(campaign_dir)  # A1 has L2+L3, A5 has only L2
    out1 = tmp_path / "resumo_l2_vs_l3.pdf"
    out2 = tmp_path / "resumo_tendencia.pdf"

    cf.plot_resumo_l2_vs_l3(cases, out1)
    cf.plot_resumo_tendencia(cases, out2)

    assert out1.stat().st_size > 0
    assert out2.stat().st_size > 0
