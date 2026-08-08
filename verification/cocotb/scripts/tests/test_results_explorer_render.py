import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import results_explorer_render as render


def test_case_id_extracts_short_identifier_from_folder_name():
    assert render.case_id(Path("A5_tacc5s_load000")) == "A5"
    assert render.case_id(Path("S0_l4")) == "S0"
    assert render.case_id(Path("B2_step050_to100")) == "B2"


def test_case_label_uses_known_case_info():
    label = render.case_label(Path("A1_tacc0p5s_load000"))
    assert label == render.CASE_INFO["A1"]["nome"]


def test_case_label_falls_back_to_folder_name_for_unknown_case():
    label = render.case_label(Path("caso_desconhecido_xyz"))
    assert label == "caso_desconhecido_xyz"


def test_flatten_metrics_flattens_known_window_blocks():
    metrics = {
        "partida": {"nrmse": 0.05, "pico_a": 12.3},
        "regime": {"nrmse": 0.01},
        "vdc": 300,
    }

    df = render.flatten_metrics(metrics)

    assert list(df.columns) == ["janela", "métrica", "valor"]
    assert set(df["janela"]) == {"partida", "regime"}
    assert len(df) == 3


def test_flatten_metrics_falls_back_to_flat_view_without_known_windows():
    metrics = {"nrmse": 0.02, "vdc": 300}

    df = render.flatten_metrics(metrics)

    assert list(df.columns) == ["métrica", "valor"]
    assert len(df) == 2


def test_has_data_true_for_run_with_recognized_csv(tmp_path):
    run_dir = tmp_path / "l2_vf_500ms_realts"
    run_dir.mkdir()
    (run_dir / "vf_vhdl_vs_c.csv").write_text("t_s,vhdl_ia,ref_ia\n0,0,0\n")

    assert render.has_data(run_dir) is True


def test_has_data_false_for_run_without_csv_or_npz(tmp_path):
    run_dir = tmp_path / "raw"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text("{}")

    assert render.has_data(run_dir) is False
