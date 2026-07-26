"""Verificação independente do Δfase (fundamental) citado no quad:l4-metricas.

Achado da auditoria de 2026-07-25: `hilbin_vs_c.py::_metrics` calcula
`ia_fund_delta_pct` (amplitude) e `speed_mean_{fpga,c}` (usados para a coluna
Δω = |diferença de médias|), mas NÃO calcula fase alguma — não há função de
fase em `fpga_vs_c.py` nem em `hilbin_vs_c.py`. Este script recomputa a fase
fundamental por detecção síncrona (projeção em seno/cosseno na frequência
dominante estimada por FFT do modelo C) para os 6 casos L4 e compara ao que
está no `.tex`, de forma independente e reproduzível.

Uso: cd verification/cocotb && uv run python scripts/l4_phase_check.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import l4_figures as l4f

CAMPAIGN = Path(__file__).resolve().parents[3] / "verification/results/2026-07-25_campaign_l4_final"

# Δfase citados no quad:l4-metricas (4-Resultados.tex, linhas 989-994), graus.
TEXT_DELTA_PHASE_DEG = {
    "S0": 0.02, "A1": -0.30, "A3": 0.89, "A5": -0.14, "B1": 0.71, "B2": 1.22,
}
# Δamplitude citados no mesmo quadro, %.
TEXT_DELTA_AMP_PCT = {
    "S0": -0.33, "A1": -0.28, "A3": 0.03, "A5": 0.34, "B1": -0.4, "B2": None,
}


def _dominant_freq_hz(i_alpha: np.ndarray, i_beta: np.ndarray, t: np.ndarray) -> float:
    """Frequência instantânea média do vetor espacial complexo (muito mais
    precisa que o pico de uma FFT com resolução de poucos Hz/bin em janelas
    curtas — um erro de frequência de 0,1 Hz já desvia a fase em graus ao
    longo de meio segundo)."""
    z = i_alpha + 1j * i_beta
    phase = np.unwrap(np.angle(z))
    freq = np.gradient(phase, t) / (2 * np.pi)
    return float(np.median(freq))


def _fundamental_amp_phase(x: np.ndarray, t: np.ndarray, f0: float) -> tuple[float, float]:
    c = np.cos(2 * np.pi * f0 * t)
    s = np.sin(2 * np.pi * f0 * t)
    ac = x - np.mean(x)
    I = 2.0 / len(x) * np.sum(ac * c)
    Q = 2.0 / len(x) * np.sum(ac * s)
    amp = float(np.hypot(I, Q))
    phase_deg = float(np.degrees(np.arctan2(Q, I)))
    return amp, phase_deg


def _wrap_deg(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def check_case(case: dict) -> dict:
    t_ms, data = l4f.load_segment(case, "regime", campaign=CAMPAIGN)
    t = t_ms / 1000.0
    t = t - t[0]
    dt = float(np.median(np.diff(t)))
    ia_c = data["ref_i_alpha"]
    ia_f = data["vhdl_i_alpha"]
    f0 = _dominant_freq_hz(data["ref_i_alpha"], data["ref_i_beta"], t)
    amp_c, phase_c = _fundamental_amp_phase(ia_c, t, f0)
    amp_f, phase_f = _fundamental_amp_phase(ia_f, t, f0)
    delta_amp_pct = 100.0 * (amp_f - amp_c) / amp_c
    delta_phase_deg = _wrap_deg(phase_f - phase_c)
    return {
        "case": case["id"], "f0_hz": round(f0, 3),
        "amp_fpga": round(amp_f, 4), "amp_c": round(amp_c, 4),
        "delta_amp_pct": round(delta_amp_pct, 3),
        "delta_phase_deg": round(delta_phase_deg, 3),
    }


def main() -> None:
    results = [check_case(c) for c in l4f.CASES_L4]
    print(f"{'caso':<4} {'f0[Hz]':>8} {'Δamp%[calc]':>12} {'Δamp%[tex]':>11} "
          f"{'Δfase[calc]':>12} {'Δfase[tex]':>11}")
    for r in results:
        cid = r["case"]
        tex_amp = TEXT_DELTA_AMP_PCT.get(cid)
        tex_phase = TEXT_DELTA_PHASE_DEG.get(cid)
        tex_amp_s = f"{tex_amp:.2f}" if tex_amp is not None else "n/d"
        tex_phase_s = f"{tex_phase:.2f}" if tex_phase is not None else "n/d"
        print(f"{cid:<4} {r['f0_hz']:>8.3f} {r['delta_amp_pct']:>12.3f} {tex_amp_s:>11} "
              f"{r['delta_phase_deg']:>12.3f} {tex_phase_s:>11}")
    out = Path(__file__).resolve().parents[2].parent / "docs/results-chapter/l4_phase_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSalvo em {out}")


if __name__ == "__main__":
    main()
