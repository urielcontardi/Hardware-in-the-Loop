import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import results_explorer_data as red


def test_list_campaigns_returns_sorted_campaign_dirs(tmp_path):
    (tmp_path / "2026-06-29_campaign_01").mkdir()
    (tmp_path / "2026-07-04_campaign_03").mkdir()
    (tmp_path / "unrelated_dir").mkdir()
    (tmp_path / "some_file.txt").write_text("x")

    campaigns = red.list_campaigns(tmp_path)

    assert [c.name for c in campaigns] == ["2026-06-29_campaign_01", "2026-07-04_campaign_03"]


def test_list_campaigns_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist"

    assert red.list_campaigns(missing) == []


def test_list_cases_excludes_dashboard_and_hidden(tmp_path):
    (tmp_path / "A1_tacc0p5s_load000").mkdir()
    (tmp_path / "campaign_dashboard").mkdir()
    (tmp_path / ".hidden").mkdir()

    cases = red.list_cases(tmp_path)

    assert [c.name for c in cases] == ["A1_tacc0p5s_load000"]


def test_list_runs_returns_sorted_subdirs(tmp_path):
    (tmp_path / "l3_top_pwm_replay_vf_2s").mkdir()
    (tmp_path / "l2_vf_2s_realts").mkdir()

    runs = red.list_runs(tmp_path)

    assert [r.name for r in runs] == ["l2_vf_2s_realts", "l3_top_pwm_replay_vf_2s"]


def test_find_timeseries_csv_picks_first_candidate_in_priority_order(tmp_path):
    (tmp_path / "sine_vhdl_vs_c.csv").write_text("t_us\n0\n")
    (tmp_path / "vf_vhdl_vs_c.csv").write_text("t_us\n0\n")

    found = red.find_timeseries_csv(tmp_path)

    assert found.name == "vf_vhdl_vs_c.csv"


def test_find_timeseries_csv_returns_none_when_no_candidate(tmp_path):
    (tmp_path / "metrics.json").write_text("{}")

    assert red.find_timeseries_csv(tmp_path) is None


def test_detect_channel_pairs_matches_ref_prefix_and_ignores_unpaired(tmp_path):
    csv_path = tmp_path / "vf_vhdl_vs_c.csv"
    csv_path.write_text("t_us,vhdl_i_alpha,ref_i_alpha,vhdl_lonely\n0,0.1,0.1,9\n")

    pairs = red.detect_channel_pairs(csv_path)

    assert len(pairs) == 1
    assert pairs[0].suffix == "i_alpha"
    assert pairs[0].vhdl_col == "vhdl_i_alpha"
    assert pairs[0].ref_col == "ref_i_alpha"


def test_detect_channel_pairs_falls_back_to_c_prefix(tmp_path):
    csv_path = tmp_path / "fullstack_vs_top.csv"
    csv_path.write_text("t_s,vhdl_speed,c_speed\n0,0.0,0.0\n")

    pairs = red.detect_channel_pairs(csv_path)

    assert pairs == [red.ChannelPair(suffix="speed", vhdl_col="vhdl_speed", ref_col="c_speed")]


def test_detect_time_column_prefers_t_s(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("t_s,vhdl_speed\n0,0\n")

    assert red.detect_time_column(csv_path) == ("t_s", 1.0)


def test_detect_time_column_falls_back_to_t_us_scaled(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("t_us,vhdl_speed\n0,0\n")

    assert red.detect_time_column(csv_path) == ("t_us", 1e-6)


def test_load_metrics_returns_metrics_subkey(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": {"nrmse_i_alpha": 0.03}}))

    assert red.load_metrics(tmp_path) == {"nrmse_i_alpha": 0.03}


def test_load_metrics_missing_file_returns_none(tmp_path):
    assert red.load_metrics(tmp_path) is None
