#ifndef GPIO_H
#define GPIO_H

#include <stdint.h>

/* ── HIL_Regs_AXI — AXI4-Lite custom slave ────────────────────────────────
 * Register map (byte offsets from base):
 *   0x00  va_ref           write — signed int32, ±CARRIER_MAX
 *   0x04  vb_ref           write
 *   0x08  vc_ref           write
 *   0x0C  pwm_ctrl         write — bit0=enable, bit1=clear_fault,
 *                                  bit2=solver_reset (1=hold solver in reset),
 *                                  [31:3]=decim
 *   0x10  vdc_word         write — Q18.14 signed (V)
 *   0x14  torque_word      write — Q18.14 signed (N·m)
 *   0x18  DEBUG_MAGIC      read  — 0x48494C52 ("HILR")
 *   0x1C  debug_status     read  — bitfield (rst_n, enable, busy, ...)
 *   0x20  free_run_ctr     read  — clock vivo
 *   0x24  carrier_tick_ctr read  — ticks do NPC carrier
 *   0x28  timer_tick_ctr   read  — ticks do timer do TIM_Solver
 *   0x2C  data_valid_latch read  — bit[0]=1: solver produziu saída
 */
#define ADDR_HIL_REGS        0x43C00000U
#define REG_VA_REF           0x00U
#define REG_VB_REF           0x04U
#define REG_VC_REF           0x08U
#define REG_PWM_CTRL         0x0CU
#define REG_VDC_WORD         0x10U
#define REG_TORQUE_WORD      0x14U
#define REG_DEBUG_MAGIC      0x18U
#define REG_DEBUG_STATUS     0x1CU
#define REG_DEBUG_FREE_RUN   0x20U
#define REG_DEBUG_CARRIER    0x24U
#define REG_DEBUG_TIMER      0x28U
#define REG_DEBUG_DV_LATCH   0x2CU

/* ── AXI GPIO — monitor (PL writes, PS reads) ─────────────────────────── */
#define ADDR_GPIO_MONITOR_1   0x41200000U  /* ch1=ialpha_mon,     ch2=ibeta_mon      */
#define ADDR_GPIO_MONITOR_2   0x41210000U  /* ch1=flux_alpha_mon, ch2=flux_beta_mon  */
#define ADDR_GPIO_MONITOR_3   0x41220000U  /* ch1=speed_mon,      ch2=data_valid_mon */

/* AXI GPIO register offsets (for monitor reads) */
#define GPIO_CH1_OFFSET  0x000
#define GPIO_CH2_OFFSET  0x008

/* pwm_ctrl bits */
#define PWM_CTRL_ENABLE       (1 << 0)
#define PWM_CTRL_CLEAR_FAULT  (1 << 1)
#define PWM_CTRL_SOLVER_RESET (1 << 2)
#define PWM_CTRL_DECIM_SHIFT  3

/* CARRIER_MAX: 100 MHz / (1 kHz * 2) = 50000 */
#define CARRIER_MAX  50000

int  gpio_init(void);
void gpio_deinit(void);

void     gpio_write(uint32_t base, uint32_t offset, uint32_t val);
uint32_t gpio_read (uint32_t base, uint32_t offset);

/* Helpers — write to HIL_Regs_AXI */
void gpio_set_vref(int32_t va, int32_t vb, int32_t vc);
void gpio_set_pwm_ctrl(int enable, int clear_fault, int solver_reset,
                       uint32_t decim_ratio);
void gpio_set_vdc_torque(int32_t vdc_word, int32_t torque_word);

/* Helpers — read from AXI GPIO monitors */
int32_t  gpio_get_speed(void);
int32_t  gpio_get_ialpha(void);
int32_t  gpio_get_ibeta(void);
int32_t  gpio_get_flux_alpha(void);
int32_t  gpio_get_flux_beta(void);
int      gpio_get_data_valid(void);

#endif /* GPIO_H */
