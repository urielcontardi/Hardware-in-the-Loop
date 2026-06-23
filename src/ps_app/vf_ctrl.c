#include "vf_ctrl.h"
#include "gpio.h"

#include <math.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>

/* V/F nominal operating point */
#define FREQ_NOM_HZ   60.0f   /* Hz  — frequência nominal (matches cocotb F_NOMINAL_HZ) */
#define V_NOM_PU      1.0f    /* pu  — tensão nominal (100% modulação) */
#define TS            (1.0f / (float)VF_TICK_HZ)  /* s — passo = 1/taxa do tick */

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
static pthread_mutex_t  tick_mutex = PTHREAD_MUTEX_INITIALIZER;
static vf_params_t      params = {
    .freq_hz      = 0.0f,
    .vdc_v        = 1240.0f,   /* V_phase_peak = Vdc/2 = 620 V → matches cocotb/PSIM V_PEAK_NOMINAL */
    .torque_nm    = 0.0f,
    .base_freq_hz = FREQ_NOM_HZ,
    .max_v_pu     = V_NOM_PU,
    .accel_time_s = 1.0f,      /* ramp = base_freq/accel = 60/1 = 60 Hz/s → matches cocotb ACC_RAMP_HZ_S */
    .enable       = 0,
    .decim        = 0,
};

static float theta     = 0.0f;  /* ângulo elétrico acumulado [rad] */
static float f_current = 0.0f;  /* frequência real após rampa [Hz] */

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
    gpio_set_pwm_ctrl(0, 0, 0, 0);
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

float vf_get_freq_actual(void)
{
    pthread_mutex_lock(&tick_mutex);
    float value = f_current;
    pthread_mutex_unlock(&tick_mutex);
    return value;
}

void vf_tick(void)
{
    pthread_mutex_lock(&tick_mutex);
    vf_params_t p;
    pthread_mutex_lock(&params_mutex);
    p = params;
    pthread_mutex_unlock(&params_mutex);

    if (!p.enable) {
        f_current = 0.0f;
        gpio_set_vref(0, 0, 0);
        gpio_set_pwm_ctrl(0, 0, 0, (uint32_t)p.decim);
        pthread_mutex_unlock(&tick_mutex);
        return;
    }

    /* Frequency ramp: advance f_current toward freq_hz at base_freq/accel_time_s Hz/s */
    float f_target = p.freq_hz < 0.0f ? 0.0f : p.freq_hz;
    float base_freq = p.base_freq_hz > 0.0f ? p.base_freq_hz : FREQ_NOM_HZ;
    float accel = p.accel_time_s > 0.0f ? (base_freq / p.accel_time_s) : 1e6f;
    float step = accel * TS;
    if (f_current < f_target)
        f_current = f_current + step > f_target ? f_target : f_current + step;
    else if (f_current > f_target)
        f_current = f_current - step < f_target ? f_target : f_current - step;

    /* V/F ratio — voltage tracks frequency proportionally, no boost */
    float max_v_pu = p.max_v_pu > 0.0f ? p.max_v_pu : V_NOM_PU;
    if (max_v_pu > 1.0f) max_v_pu = 1.0f;
    float v_pu = max_v_pu * (f_current / base_freq);
    if (v_pu > max_v_pu) v_pu = max_v_pu;

    /* Integra ângulo com a frequência real (após rampa) */
    float omega = 2.0f * (float)M_PI * f_current;
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
    gpio_set_pwm_ctrl(1, 0, 0, (uint32_t)p.decim);
    pthread_mutex_unlock(&tick_mutex);
}

/*
 * vf_reset_solver
 *  Pulsa o bit solver_reset do pwm_ctrl para zerar os estados integradores
 *  do TIM_Solver (Iα/β, Φα/β, ω). Serializa com vf_tick para impedir que uma
 *  atualização da portadora limpe o bit durante o pulso. A duração de 2 ms é
 *  >> que o período do solver (27
 *  ciclos @100 MHz ≈ 270 ns).
 *
 *  Pré-condição implícita: o chamador já zerou o enable em vf_params (ou
 *  vai zerar logo depois), pois durante o pulso o motor fica indefinido.
 */
void vf_reset_solver(void)
{
    pthread_mutex_lock(&tick_mutex);

    vf_params_t p;
    pthread_mutex_lock(&params_mutex);
    p = params;
    p.enable = 0;
    params = p;
    pthread_mutex_unlock(&params_mutex);

    gpio_set_vref(0, 0, 0);
    gpio_set_vdc_torque(0, 0);
    gpio_set_pwm_ctrl(0, 0, 1, (uint32_t)p.decim);  /* assert solver_reset */
    usleep(2000);
    gpio_set_pwm_ctrl(0, 0, 0, (uint32_t)p.decim);  /* release */

    theta     = 0.0f;
    f_current = 0.0f;
    pthread_mutex_unlock(&tick_mutex);
}
