#ifndef VF_CTRL_H
#define VF_CTRL_H

#include <stdint.h>

/*
 * V/F open-loop controller
 *
 * Parâmetros configuráveis via UDP:
 *   freq_hz   — frequência elétrica de saída [Hz]
 *   vdc_v     — tensão DC do barramento [V]
 *   torque_nm — torque de carga [N·m]  (passa direto ao solver)
 *   base_freq_hz — frequência nominal/base do V/F [Hz]
 *   max_v_pu  — tensão máxima de modulação [pu]
 *   boost_v_pu — boost de baixa frequência [pu]
 *   enable    — 0=desligado, 1=ligado
 *   decim     — decimation ratio (0 = default 375 → 10 kHz DMA output)
 *
 * Escala interna:
 *   V/F ratio : V_ref = V_NOM * (freq_hz / FREQ_NOM)  (com saturação em V_NOM)
 *   vrefs     : escala ±CARRIER_MAX = ±75000 (100% modulação)
 *   vdc/torque: Q31 com escala definida em vf_ctrl.c (ajuste conforme seu sistema)
 */

typedef struct {
    float freq_hz;    /* frequência elétrica [Hz] — default 0 */
    float vdc_v;      /* tensão DC [V]             — default 300 */
    float torque_nm;  /* torque de carga [N·m]     — default 0   */
    float base_freq_hz; /* frequência base V/F [Hz] — default 50  */
    float max_v_pu;     /* tensão máxima [pu]       — default 1   */
    float boost_v_pu;   /* boost baixa freq [pu]    — default 0   */
    int   enable;     /* 0=off, 1=on               — default 0   */
    int   decim;      /* decimation ratio           — default 0   */
} vf_params_t;

int  vf_init(void);
void vf_deinit(void);

/* Atualiza parâmetros (thread-safe via mutex) */
void vf_set_params(const vf_params_t *p);
void vf_get_params(vf_params_t *p);

/* Chamado a cada tick de 1 kHz (SIGALRM) */
void vf_tick(void);

#endif /* VF_CTRL_H */
