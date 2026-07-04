#!/usr/bin/env bash
# Re-executa toda a matriz S0/A1-A5 do Grupo A com os parametros de motor
# corrigidos (Rs=0.4396, J=0.4 — motor "LVP 760V" real, ver
# verification/results/2026-07-04_campaign_02/manifest.json).
#
# Historico: ate 2026-07-03 os testes usavam Rs=0.435 / J=0.192, herdados de
# um rotulo incorreto ("0.75 kW ref") em src/rtl/HIL_AXI_Top.vhd. Isso foi
# corrigido junto com um bug anterior no torque nominal (Tn), que ja tinha
# motivado uma rodada de re-execucao (ver run_grupo_a_torque_fix.sh, agora
# obsoleto). Como J entra na dinamica mecanica mesmo com carga zero, essa
# correcao invalida TODOS os resultados anteriores — inclusive S0 e A1, que
# nao eram afetados pelo bug do Tn.
#
# Casos cobertos aqui: A1, A2, A3, A4, A5, e o diagnostico de rotor travado
# (locked rotor) do estudo S0. O restante do estudo S0 (l2_sine_60hz_realts,
# l2_vf_50ms_realts, l2_vf_2s_realts, l2_const_12hz_*, l3_top_pwm_replay_*,
# l3_fullstack_*) nao tem script salvo — foi rodado via comandos avulsos ou
# via campanha JSON (verification/cocotb/campaigns/l3_pwm_replay.json, ja
# atualizado para o novo campaign_id) e precisa ser reexecutado separadamente
# usando os mesmos parametros de antes, so trocando Rs/J.
#
# Uso:
#   bash verification/cocotb/campaigns/run_campanha_02_motor_fix.sh 2>&1 | tee /tmp/run_campanha_02_motor_fix.log

set -uo pipefail
cd "$(dirname "$0")"

LOG_DIR="../../../verification/results/2026-07-04_campaign_02"
STAMP="$(date +%Y%m%dT%H%M%S)"

run_step() {
    local name="$1"
    local script="$2"
    local log_file="$3"
    echo "=========================================================="
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INICIANDO: ${name}"
    echo "  script: ${script}"
    echo "  log:    ${log_file}"
    echo "=========================================================="
    mkdir -p "$(dirname "${log_file}")"
    if bash "${script}" >"${log_file}" 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OK: ${name}"
        return 0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] FALHOU: ${name} (ver ${log_file})"
        return 1
    fi
}

STATUS=0

run_step "A1 L2 (vf 500ms, carga 0)" \
    "run_a1_l2_vf_500ms.sh" \
    "${LOG_DIR}/A1_tacc0p5s_load000/run_l2_${STAMP}.log" || STATUS=1

run_step "A2 L2 (vf 500ms, Tn=116.7136249340566)" \
    "run_a2_l2_vf_500ms.sh" \
    "${LOG_DIR}/A2_tacc0p5s_load100/run_l2_${STAMP}.log" || STATUS=1

run_step "A3 L2 (vf 1s, 0.5xTn=58.3568124670283)" \
    "run_a3_l2_vf_1s.sh" \
    "${LOG_DIR}/A3_tacc1s_load050/run_l2_${STAMP}.log" || STATUS=1

run_step "A4 L2 (vf 2s, Tn=116.7136249340566)" \
    "run_a4_l2_vf_2s.sh" \
    "${LOG_DIR}/A4_tacc2s_load100/run_l2_${STAMP}.log" || STATUS=1

run_step "A5 L2 (vf 5s, carga 0)" \
    "run_a5_l2_vf_5s.sh" \
    "${LOG_DIR}/A5_tacc5s_load000/run_l2_${STAMP}.log" || STATUS=1

run_step "S0 locked-rotor diagnostic (J=1e6, carga 0)" \
    "run_l2_lockedrotor_vf_300ms.sh" \
    "${LOG_DIR}/S0_tacc1s_load000/run_lockedrotor_${STAMP}.log" || STATUS=1

run_step "A2 L3 (pwm replay vf 500ms, Tn=116.7136249340566) — historicamente bloqueado por sandbox bwrap" \
    "run_a2_l3_vf_500ms.sh" \
    "${LOG_DIR}/A2_tacc0p5s_load100/run_l3_${STAMP}.log" || STATUS=1

echo "=========================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bateria concluida. status final=${STATUS}"
echo "Pendente apos esta bateria (fazer manualmente):"
echo "  - Reexecutar o restante de S0 (sine_60hz, vf_50ms, vf_2s, const_12hz_*,"
echo "    l3_top_pwm_replay_*, l3_fullstack_*) com Rs=0.4396/J=0.4 — sem script"
echo "    salvo, usar os mesmos parametros do campaign_run_summary.json antigo"
echo "  - Regenerar todos os *_comparison/comparison.json (A1xA2, A1xA2xA3, A2xA4)"
echo "  - Regenerar campaign_dashboard/summary.csv e dashboard.html"
echo "  - Atualizar manifest.json (status not_started -> l2_generated / l3_generated)"
echo "  - Atualizar capitulo 4 da dissertacao com as metricas novas de TODOS os casos"
echo "    (S0, A1-A5), nao so A2/A3/A4 como na rodada anterior"
echo "=========================================================="

exit "${STATUS}"
