import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factcheck_cap4 import extract_numbers, match_claims


def _write_tex(tex: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False, encoding="utf-8")
    f.write(tex)
    f.close()
    return Path(f.name)


def test_extract_numbers_finds_percent_and_decimal_comma():
    tex = r"""
    O NRMSE de $i_{s\alpha}=0{,}166\%$ e MAE de velocidade de
    $6{,}1\times10^{-4}~\mathrm{rad/s}$.
    """
    path = _write_tex(tex)
    claims = extract_numbers(path)
    values = sorted(c.value for c in claims)
    assert any(abs(v - 0.166) < 1e-9 for v in values)
    assert any(abs(v - 6.1e-4) < 1e-9 for v in values)


def test_extract_numbers_ignores_commented_lines():
    tex = r"% NRMSE antigo de 0{,}166\% nao deve ser considerado"
    path = _write_tex(tex)
    claims = extract_numbers(path)
    assert claims == []


def test_match_claims_flags_matching_value_as_match():
    tex = r"O NRMSE foi de $0{,}166\%$."
    path = _write_tex(tex)
    claims = extract_numbers(path)
    sources = {"l2": {"vf2s": {"i_alpha": {"nrmse": 0.00166}}}}
    results = match_claims(claims, sources)
    assert any(r.status == "match" for r in results)


def test_match_claims_flags_divergent_value_as_diverge():
    tex = r"O NRMSE foi de $5{,}0\%$."
    path = _write_tex(tex)
    claims = extract_numbers(path)
    sources = {"l2": {"vf2s": {"i_alpha": {"nrmse": 0.00166}}}}
    results = match_claims(claims, sources)
    assert any(r.status in ("diverge", "not_found") for r in results)
