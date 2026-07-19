import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l2_figures as eng


SIGS = ["i_alpha", "i_beta", "flux_alpha", "flux_beta", "speed"]


def _write_l3_csv(path: Path, time_col: str, ref_prefix: str, extra=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [time_col] + [f"vhdl_{s}" for s in SIGS] + [f"{ref_prefix}_{s}" for s in SIGS] + list(extra)
    rows = []
    for i in range(4):
        vals = [i * 1e-3] + [float(i)] * len(SIGS) + [float(i) * 1.01] * len(SIGS) + [6] * len(extra)
        rows.append(",".join(str(v) for v in vals))
    path.write_text(",".join(header) + "\n" + "\n".join(rows) + "\n")


def test_load_case_ts_time_and_c_prefix(tmp_path):
    """load_case aceita t_s e prefixo c_, canonicalizando p/ ref_ e t_ms."""
    _write_l3_csv(tmp_path / "d/fullstack_vs_top.csv", "t_s", "c", extra=("va", "vb", "vc"))
    case = {"dir": "d", "csv": "fullstack_vs_top.csv",
            "time_col": "t_s", "ref_prefix": "c", "extra_cols": ["va", "vb", "vc"]}
    t_ms, data = eng.load_case(case, tmp_path)
    # t_s -> ms : 3e-3 s == 3.0 ms na ultima amostra
    assert t_ms[-1] == pytest.approx(3.0)
    # colunas de referencia canonicalizadas para ref_*
    assert "ref_i_alpha" in data and "c_i_alpha" not in data
    assert data["ref_i_alpha"][1] == pytest.approx(1.01)
    assert data["vhdl_i_alpha"][1] == pytest.approx(1.0)
    # colunas extras preservadas
    assert data["va"][0] == pytest.approx(6.0)


def test_load_case_defaults_l2_unchanged(tmp_path):
    """Sem time_col/ref_prefix: comportamento L2 (t_us, ref_) preservado."""
    _write_l3_csv(tmp_path / "d/x.csv", "t_us", "ref")
    case = {"dir": "d", "csv": "x.csv"}
    t_ms, data = eng.load_case(case, tmp_path)
    assert t_ms[-1] == pytest.approx(3e-6)  # t_us=3e-3 -> 3e-6 ms
    assert "ref_i_alpha" in data
