"""Metricas de resposta a degrau de carga (Grupo B).

Calculadas a partir da mesma serie temporal ja coletada para o CSV/NRMSE de
cada teste L2/L3 -- nao precisa de captura de alta resolucao separada, o
record_interval ja existente (~125us de passo para os casos B1-B3) e
suficiente para capturar a dinamica eletromecanica do motor.
"""
from __future__ import annotations

import math


def compute_transient_metrics(
    t: list[float],
    speed: list[float],
    i_alpha: list[float],
    i_beta: list[float],
    t_step: float,
    settle_tol_frac: float = 0.05,
) -> dict:
    """Estatisticas de resposta a degrau para a janela t >= t_step.

    Retorna:
        speed_before_step_rad_s: velocidade na ultima amostra antes de t_step.
        speed_peak_deviation_rad_s: maior |speed(t) - speed_before_step| para t >= t_step.
        current_peak_a: maior sqrt(i_alpha^2 + i_beta^2) para t >= t_step.
        recovery_time_s: segundos desde t_step ate a velocidade permanecer
            dentro de settle_tol_frac do seu valor final (ultima amostra) ate
            o fim da janela; None se nunca assentar (exige pelo menos 2
            amostras restantes para aceitar o assentamento, evitando o caso
            trivial de "a ultima amostra sempre bate com ela mesma").
    """
    idx_before = None
    for i, ti in enumerate(t):
        if ti < t_step:
            idx_before = i
        else:
            break
    speed_before = speed[idx_before] if idx_before is not None else speed[0]

    post_idx = [i for i, ti in enumerate(t) if ti >= t_step]
    if not post_idx:
        return {
            "speed_before_step_rad_s": speed_before,
            "speed_peak_deviation_rad_s": 0.0,
            "current_peak_a": 0.0,
            "recovery_time_s": None,
        }

    speed_peak_deviation = max(abs(speed[i] - speed_before) for i in post_idx)
    current_peak = max(math.hypot(i_alpha[i], i_beta[i]) for i in post_idx)

    speed_final = speed[post_idx[-1]]
    tol = abs(speed_final) * settle_tol_frac
    recovery_time = None
    for j in range(len(post_idx)):
        remaining = post_idx[j:]
        if len(remaining) < 2:
            break
        if all(abs(speed[k] - speed_final) <= tol for k in remaining):
            recovery_time = t[post_idx[j]] - t_step
            break

    return {
        "speed_before_step_rad_s": speed_before,
        "speed_peak_deviation_rad_s": speed_peak_deviation,
        "current_peak_a": current_peak,
        "recovery_time_s": recovery_time,
    }
