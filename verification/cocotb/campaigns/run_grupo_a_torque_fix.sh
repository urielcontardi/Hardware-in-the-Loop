#!/usr/bin/env bash
# OBSOLETO (2026-07-04): superado por run_campanha_02_motor_fix.sh, que alem
# do Tn tambem corrige Rs/J (motor real, ver manifest.json da campanha 02) e
# roda contra a pasta verification/results/2026-07-04_campaign_02. Os scripts
# individuais chamados abaixo (run_a2_l2_vf_500ms.sh etc.) ja foram
# atualizados para a nova pasta/parametros; este orquestrador antigo ainda
# aponta para 2026-06-29_campaign_01 e nao deve mais ser usado.
#
# Re-executa os casos do Grupo A afetados pelo bug de torque nominal (Tn).
#
# Ate 2026-07-02, Tn foi calculado assumindo um motor de 0.75 kW (Tn=3.9788735772973833 Nm),
# rotulo herdado de um comentario desatualizado em src/rtl/HIL_AXI_Top.vhd. O motor
# realmente simulado (Rs=0.435, Rr=0.2826, Ls=3.1364mH, Lr=6.3264mH, Lm=109.9442mH) e o
# motor de 22 kW / 760 V ("LVP 760V") de extras/induction-motor-model/psim/1_modelValidation/paramSim.txt.
# Tn correto = Pn/omega_sync = 22000 / (2*pi*60/2) = 116.7136249340566 Nm.
#
# Casos afetados (carga != 0): A2 (1.0 Tn), A3 (0.5 Tn), A4 (1.0 Tn).
# A1 e A5 (carga = 0) nao sao afetados e NAO sao re-executados aqui.
#
# Uso:
#   bash verification/cocotb/campaigns/run_grupo_a_torque_fix.sh 2>&1 | tee /tmp/run_grupo_a_torque_fix.log
#
# Cada etapa grava seu proprio log em verification/results/2026-06-29_campaign_01/<caso>/rerun_<timestamp>.log
# e so avanca para a proxima se a anterior terminar (sucesso ou falha registrada); uma falha
# isolada (ex.: L3 do A2, historicamente bloqueado por sandbox bwrap) nao aborta o restante.

set -uo pipefail
cd "$(dirname "$0")"

LOG_DIR="../../../verification/results/2026-06-29_campaign_01"
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

run_step "A2 L2 (vf 500ms, Tn=116.7136249340566)" \
    "run_a2_l2_vf_500ms.sh" \
    "${LOG_DIR}/A2_tacc0p5s_load100/rerun_l2_${STAMP}.log" || STATUS=1

run_step "A3 L2 (vf 1s, 0.5xTn=58.3568124670283)" \
    "run_a3_l2_vf_1s.sh" \
    "${LOG_DIR}/A3_tacc1s_load050/rerun_l2_${STAMP}.log" || STATUS=1

run_step "A4 L2 (vf 2s, Tn=116.7136249340566)" \
    "run_a4_l2_vf_2s.sh" \
    "${LOG_DIR}/A4_tacc2s_load100/rerun_l2_${STAMP}.log" || STATUS=1

run_step "A2 L3 (pwm replay vf 500ms, Tn=116.7136249340566) — historicamente bloqueado por sandbox bwrap" \
    "run_a2_l3_vf_500ms.sh" \
    "${LOG_DIR}/A2_tacc0p5s_load100/rerun_l3_${STAMP}.log" || STATUS=1

echo "=========================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bateria concluida. status final=${STATUS}"
echo "Pendente apos esta bateria (fazer manualmente):"
echo "  - Regenerar verification/results/2026-06-29_campaign_01/A2_tacc0p5s_load100/a1_vs_a2_l2_comparison/comparison.json"
echo "  - Regenerar verification/results/2026-06-29_campaign_01/A3_tacc1s_load050/a1_a2_a3_l2_comparison"
echo "  - Regenerar verification/results/2026-06-29_campaign_01/A4_tacc2s_load100/a2_vs_a4_l2_comparison"
echo "  - Regenerar campaign_dashboard/summary.csv e dashboard.html"
echo "  - Atualizar manifest.json (status STALE_torque_bug_pending_rerun -> l2_generated / l3_generated)"
echo "  - Atualizar capitulo 4 da dissertacao com as metricas novas de A2/A3/A4"
echo "=========================================================="

exit "${STATUS}"
