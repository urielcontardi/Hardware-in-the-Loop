#ifndef GPIO_H
#define GPIO_H

#include <stdint.h>

/* AXI GPIO base addresses */
#define ADDR_GPIO_MONITOR_1   0x41200000U  /* ch1=ialpha_mon,     ch2=ibeta_mon      */
#define ADDR_GPIO_MONITOR_2   0x41210000U  /* ch1=flux_alpha_mon, ch2=flux_beta_mon  */
#define ADDR_GPIO_MONITOR_3   0x41220000U  /* ch1=speed_mon,      ch2=data_valid_mon */
#define ADDR_GPIO_VDC_TORQUE  0x41230000U  /* ch1=vdc_word,       ch2=torque_word    */
#define ADDR_GPIO_VREF_AB     0x41240000U  /* ch1=va_ref,         ch2=vb_ref         */
#define ADDR_GPIO_VREF_C      0x41250000U  /* ch1=vc_ref,         ch2=pwm_ctrl       */

/* AXI GPIO register offsets */
#define GPIO_CH1_OFFSET  0x000
#define GPIO_CH2_OFFSET  0x008

/* pwm_ctrl bits */
#define PWM_CTRL_ENABLE      (1 << 0)
#define PWM_CTRL_CLEAR_FAULT (1 << 1)
/* pwm_ctrl[31:2] = decim_ratio */
#define PWM_CTRL_DECIM_SHIFT 2

/* CARRIER_MAX: 150 MHz / (1 kHz * 2) = 75000 */
#define CARRIER_MAX  75000

int  gpio_init(void);
void gpio_deinit(void);

void     gpio_write(uint32_t base, uint32_t offset, uint32_t val);
uint32_t gpio_read (uint32_t base, uint32_t offset);

/* Helpers */
void gpio_set_vref(int32_t va, int32_t vb, int32_t vc);
void gpio_set_pwm_ctrl(int enable, int clear_fault, uint32_t decim_ratio);
void gpio_set_vdc_torque(int32_t vdc_q31, int32_t torque_q31);

int32_t  gpio_get_speed(void);
int32_t  gpio_get_ialpha(void);
int32_t  gpio_get_ibeta(void);
int32_t  gpio_get_flux_alpha(void);
int32_t  gpio_get_flux_beta(void);
int      gpio_get_data_valid(void);

#endif /* GPIO_H */
