"""Valida a matriz de 22 experimentos da campaign_03 (arquivo de dados puro,
sem depender de simulador)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MATRIX_PATH = (
    Path(__file__).resolve().parents[2]
    / "campaigns" / "campaign_03_full_matrix.json"
)


def _load():
    return json.loads(MATRIX_PATH.read_text())


def test_matrix_has_22_experiments():
    config = _load()
    assert len(config["experiments"]) == 22


def test_all_experiment_ids_are_unique():
    config = _load()
    ids = [e["id"] for e in config["experiments"]]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


def test_all_output_dirs_are_unique():
    config = _load()
    dirs = [e["output_dir"] for e in config["experiments"]]
    assert len(dirs) == len(set(dirs)), f"duplicate output_dir: {dirs}"


def test_cocotb_experiments_have_required_fields():
    config = _load()
    for exp in config["experiments"]:
        if exp["runner"] != "cocotb":
            continue
        assert "level" in exp
        assert "duration_s" in exp
        if exp["level"] == "l2":
            assert exp["test_mode"] in ("vf", "sine")
            # test_tim_solver_sine.py has no CSV decimation support (unlike
            # the vf test's HIL_VF_RECORD_INTERVAL), so record_interval would
            # be dead config for sine — only required for vf.
            if exp["test_mode"] == "vf":
                assert "record_interval" in exp
        if exp["level"] == "l3":
            assert exp["ref_mode"] in ("vf", "fixed")
            assert "record_interval" in exp


def test_fullstack_mock_experiments_depend_on_existing_cocotb_case():
    config = _load()
    ids = {e["id"] for e in config["experiments"]}
    for exp in config["experiments"]:
        if exp["runner"] != "fullstack_mock":
            continue
        assert exp["depends_on"] in ids


def test_case_ids_match_manifest():
    config = _load()
    manifest = json.loads(
        (Path(__file__).resolve().parents[3]
         / "results" / "2026-07-04_campaign_03" / "manifest.json").read_text()
    )
    manifest_ids = {c["id"] for c in manifest["cases"]}
    matrix_case_ids = {e["case_id"] for e in config["experiments"]}
    assert matrix_case_ids == manifest_ids
