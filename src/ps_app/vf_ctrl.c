#include "vf_ctrl.h"
#include "gpio.h"

#include <math.h>
#include <string.h>
#include <pthread.h>

/* V/F nominal operating point */
#define FREQ_NOM_HZ   50.0f   /* Hz  — frequência nominal */
#define V_NOM_PU      1.0f    /* pu  — tensão nominal (100% modulação) */
#define TS            0.001f  /* s   — período do tick (1 kHz) */

/*
 * Vdc e torque: Q18.14 signed em int32 (14 bits fracionários).
 *   Resolução: ~61 µV / µN·m
 *   FPGA converte para Q14.28 via shift_left(14).
 *   Máx. físico: ±8192 (limite Q14.28 no solver).
 */
#define PS_FRAC_BITS   14
#define PS_FRAC_SCALE  ((float)(1 << PS_FRAC_BITS))   /* 16384.0f */
#define PS_MAX_PHYS    8000.0f                        /* margem de segurança */

static pthread_mutex_t  params_mutex = PTHREAD_MUTEX_INITIALIZER;
static vf_params_t      params = {
    .freq_hz   = 0.0f,
    .vdc_v     = 300.0f,
    .torque_nm = 0.0f,
    .base_freq_hz = FREQ_NOM_HZ,
    .max_v_pu     = V_NOM_PU,
    .boost_v_pu   = 0.0f,
    .enable    = 0,
    .decim     = 0,
};

static float theta = 0.0f;   /* ângulo elétrico acumulado [rad] */

/* Converte um valor físico (V ou N·m) em Q18.14 signed, saturado */
static inline int32_t float_to_q18_14(float x)
{
    if (x >  PS_MAX_PHYS) x =  PS_MAX_PHYS;
    if (x < -PS_MAX_PHYS) x = -PS_MAX_PHYS;
    return (int32_t)(x * PS_FRAC_SCALE);
}

int vf_init(void)
{
    theta = 0.0f;
    return 0;
}

void vf_deinit(void)
{
    /* desliga saída ao sair */
    gpio_set_vref(0, 0, 0);
    gpio_set_pwm_ctrl(0, 0, 0);
}

void vf_set_params(const vf_params_t *p)
{
    pthread_mutex_lock(&params_mutex);
    params = *p;
    pthread_mutex_unlock(&params_mutex);
}

void vf_get_params(vf_params_t *p)
{
    pthread_mutex_lock(&params_mutex);
    *p = params;
    pthread_mutex_unlock(&params_mutex);
}

void vf_tick(void)
{
    vf_params_t p;
    pthread_mutex_lock(&params_mutex);
    p = params;
    pthread_mutex_unlock(&params_mutex);

    if (!p.enable) {
        gpio_set_vref(0, 0, 0);
        gpio_set_pwm_ctrl(0, 0, (uint32_t)p.decim);
        return;
    }

    /* V/F ratio */
    float freq = p.freq_hz;
    if (freq < 0.0f) freq = 0.0f;

    float base_freq = p.base_freq_hz;
    if (base_freq <= 0.0f) base_freq = FREQ_NOM_HZ;

    float max_v_pu = p.max_v_pu;
    if (max_v_pu <= 0.0f) max_v_pu = V_NOM_PU;
    if (max_v_pu > 1.0f) max_v_pu = 1.0f;

    float boost_v_pu = p.boost_v_pu;
    if (boost_v_pu < 0.0f) boost_v_pu = 0.0f;
    if (boost_v_pu > max_v_pu) boost_v_pu = max_v_pu;

    float v_pu = boost_v_pu + (max_v_pu - boost_v_pu) * (freq / base_freq);
    if (v_pu > max_v_pu) v_pu = max_v_pu;

    /* Integra ângulo */
    float omega = 2.0f * (float)M_PI * freq;
    theta += omega * TS;
    if (theta > 2.0f * (float)M_PI)
        theta -= 2.0f * (float)M_PI;

    /* Referências trifásicas em pu, escaladas para ±CARRIER_MAX */
    float scale = v_pu * (float)CARRIER_MAX;
    int32_t va = (int32_t)(scale * sinf(theta));
    int32_t vb = (int32_t)(scale * sinf(theta - 2.0f * (float)M_PI / 3.0f));
    int32_t vc = (int32_t)(scale * sinf(theta + 2.0f * (float)M_PI / 3.0f));

    /* Vdc e torque em Q18.14 (FPGA converte para Q14.28 via shift_left 14) */
    int32_t vdc_q18_14    = float_to_q18_14(p.vdc_v);
    int32_t torque_q18_14 = float_to_q18_14(p.torque_nm);

    gpio_set_vdc_torque(vdc_q18_14, torque_q18_14);
    gpio_set_vref(va, vb, vc);
    gpio_set_pwm_ctrl(1, 0, (uint32_t)p.decim);
}
