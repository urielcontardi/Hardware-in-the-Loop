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
 * Escala Q31 para Vdc e Torque:
 *   INT32_MAX  (0x7FFFFFFF) = VDC_MAX_V (ex: 600 V)
 *   INT32_MAX               = TORQUE_MAX_NM (ex: 50 N·m)
 */
#define VDC_MAX_V      600.0f
#define TORQUE_MAX_NM   50.0f

static pthread_mutex_t  params_mutex = PTHREAD_MUTEX_INITIALIZER;
static vf_params_t      params = {
    .freq_hz   = 0.0f,
    .vdc_v     = 300.0f,
    .torque_nm = 0.0f,
    .enable    = 0,
    .decim     = 0,
};

static float theta = 0.0f;   /* ângulo elétrico acumulado [rad] */

static inline int32_t float_to_q31(float x, float x_max)
{
    float scaled = x / x_max;
    if (scaled >  1.0f) scaled =  1.0f;
    if (scaled < -1.0f) scaled = -1.0f;
    return (int32_t)(scaled * (float)INT32_MAX);
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

    float v_pu = V_NOM_PU * (freq / FREQ_NOM_HZ);
    if (v_pu > V_NOM_PU) v_pu = V_NOM_PU;

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

    /* Vdc e torque em Q31 */
    int32_t vdc_q31    = float_to_q31(p.vdc_v,     VDC_MAX_V);
    int32_t torque_q31 = float_to_q31(p.torque_nm, TORQUE_MAX_NM);

    gpio_set_vdc_torque(vdc_q31, torque_q31);
    gpio_set_vref(va, vb, vc);
    gpio_set_pwm_ctrl(1, 0, (uint32_t)p.decim);
}
