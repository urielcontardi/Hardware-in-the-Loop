#ifndef VF_CTRL_H
#define VF_CTRL_H

#include <stdint.h>

/*
 * Taxa de atualização da referência V/F [Hz]. Igual a 2x a portadora PWM
 * (1 kHz, definida por PWM_FREQ no HIL_AXI_Top sintetizado), porque a
 * referência agora é escrita a cada interrupção real da portadora — pico E
 * vale (LOAD_BOTH_EDGES, ver docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md),
 * disparada por src/ps_app/vf_irq.c. Antes deste trabalho, o tick rodava
 * livre por software (clock_nanosleep) a 1 kHz, sem travamento de fase com
 * a portadora — daí o histórico de jitter documentado na dissertação.
 * vf_ctrl.c deriva o passo de integração TS = 1/VF_TICK_HZ.
 */
#define VF_TICK_HZ  2000u

/*
 * V/F open-loop controller — linear puro, sem boost de baixa frequência.
 *
 * Lei aplicada: V_ref = max_v_pu × (f_current / base_freq_hz)
 *   Em f=0 → V=0; em f=base_freq → V=max_v_pu. Idêntico ao modulador
 *   escalar do PSIM (fonte de tensão senoidal com razão V/f constante).
 *
 * Parâmetros configuráveis via UDP:
 *   freq_hz      — frequência elétrica alvo [Hz]
 *   vdc_v        — tensão DC do barramento [V]  (V_fase_pico = Vdc/2)
 *   torque_nm    — torque de carga [N·m]  (passa direto ao solver)
 *   base_freq_hz — frequência nominal do V/F [Hz]  (default 60 Hz)
 *   max_v_pu     — tensão máxima de modulação [pu]  (default 1.0)
 *   accel_time_s — tempo para rampar 0→base_freq [s]
 *   enable       — 0=desligado, 1=ligado
 *   decim        — decimation ratio do caminho DMA/AXI-Stream
 *   telem_hz     — taxa de polling GPIO para telemetria (1000..50000 Hz)
 *
 * Escala das referências de tensão enviadas à FPGA:
 *   vrefs: signed int32 em ±CARRIER_MAX = ±(CLK_FREQ/PWM_FREQ/2)
 *          Com CLK=100 MHz e PWM=1 kHz: CARRIER_MAX = 50000 (ver gpio.h)
 *   vdc/torque: Q18.14 signed (FPGA converte para Q14.28 via shift_left 14)
 */

typedef struct {
    float freq_hz;       /* frequência elétrica alvo [Hz]          — default 0   */
    float vdc_v;         /* tensão DC [V]                          — default 300 */
    float torque_nm;     /* torque de carga [N·m]                  — default 0   */
    float base_freq_hz;  /* frequência nominal do V/F [Hz]         — default 60  */
    float max_v_pu;      /* tensão máxima de modulação [pu]        — default 1   */
    float accel_time_s;  /* tempo para rampar 0→base_freq [s]      — default 5   */
    int   enable;        /* 0=off, 1=on                            — default 0   */
    int   decim;         /* FPGA DMA decim (não afeta telem UDP)   — default 0   */
} vf_params_t;

int  vf_init(void);
void vf_deinit(void);

/* Atualiza parâmetros (thread-safe via mutex) */
void vf_set_params(const vf_params_t *p);
void vf_get_params(vf_params_t *p);

/* Chamado a cada tick (VF_TICK_HZ, via timer POSIX SIGRTMIN) */
void vf_tick(void);

/* Retorna a frequência atual após aplicação da rampa de aceleração [Hz].
 * Útil para incluir no status enviado ao host. */
float vf_get_freq_actual(void);

/*
 * Pulsa o reset síncrono do TIM_Solver via bit2 do pwm_ctrl, zerando os
 * estados integradores (correntes, fluxos, velocidade) sem reload do bitstream.
 * Força enable=0 nos parâmetros internos como efeito colateral.
 */
void vf_reset_solver(void);

#endif /* VF_CTRL_H */
