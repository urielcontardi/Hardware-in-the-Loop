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
 *   0x30  coeff_addr       write/read — [1:0]=matrix A/B/Y, [4:2]=row, [7:5]=col
 *   0x34  coeff_data_lo    write/read — coefficient[31:0] raw Q14.28
 *   0x38  coeff_data_hi    write/read — coefficient[41:32]
 *   0x3C  coeff_commit     write      — bit[0]=1 pulses coeff_we,
 *                                  bit[1]=1 atomically applies shadow model
 *   0x40  pwm_cap_ctrl     write      — bit0=start, bit1=stop, bit2=clear
 *   0x44  pwm_cap_status   read       — bit0=active, bit1=overflow,
 *                                  bit2=empty, bit3=full, bits[31:16]=count
 *   0x48  pwm_cap_window   write/read — capture window cycles, 0=continuous
 *   0x4C  pwm_cap_data_lo  read       — current event[31:0]
 *   0x50  pwm_cap_data_hi  read       — current event[63:32]
 *   0x54  pwm_cap_pop      write      — bit0 pops current event
 *   0x58  hil_time          read       — current run-local time[31:0]
 *   0x5C  hil_epoch         read       — current run epoch[15:0]
 *   0x60  fpga_version      read       — build/version tag
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
#define REG_COEFF_ADDR       0x30U
#define REG_COEFF_DATA_LO    0x34U
#define REG_COEFF_DATA_HI    0x38U
#define REG_COEFF_COMMIT     0x3CU
#define REG_PWM_CAP_CTRL     0x40U
#define REG_PWM_CAP_STATUS   0x44U
#define REG_PWM_CAP_WINDOW   0x48U
#define REG_PWM_CAP_DATA_LO  0x4CU
#define REG_PWM_CAP_DATA_HI  0x50U
#define REG_PWM_CAP_POP      0x54U
#define REG_HIL_TIME         0x58U
#define REG_HIL_EPOCH        0x5CU
#define REG_FPGA_VERSION     0x60U

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

#define TIM_COEFF_MATRIX_A 0U
#define TIM_COEFF_MATRIX_B 1U
#define TIM_COEFF_MATRIX_Y 2U
#define TIM_COEFF_ADDR(matrix, row, col)     ((((uint32_t)(matrix)) & 0x3U) | ((((uint32_t)(row)) & 0x7U) << 2) |      ((((uint32_t)(col)) & 0x7U) << 5))

#define TIM_COEFF_WRITE_STROBE  0x1U
#define TIM_COEFF_APPLY_STROBE  0x2U

#define PWM_CAP_CTRL_START 0x1U
#define PWM_CAP_CTRL_STOP  0x2U
#define PWM_CAP_CTRL_CLEAR 0x4U
#define PWM_CAP_STATUS_ACTIVE   (1U << 0)
#define PWM_CAP_STATUS_OVERFLOW (1U << 1)
#define PWM_CAP_STATUS_EMPTY    (1U << 2)
#define PWM_CAP_STATUS_FULL     (1U << 3)

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
void gpio_write_tim_coeff(uint32_t matrix, uint32_t row, uint32_t col,
                          int64_t coeff_q14_28);
void gpio_apply_tim_coeffs(void);

/* Helpers — PWM event capture readout */
void     gpio_pwmcap_clear(void);
void     gpio_pwmcap_start(void);
void     gpio_pwmcap_stop(void);
void     gpio_pwmcap_set_window(uint32_t cycles);
uint32_t gpio_pwmcap_status(void);
uint16_t gpio_pwmcap_count(void);
uint64_t gpio_pwmcap_peek(void);
void     gpio_pwmcap_pop(void);
int      gpio_pwmcap_read(uint64_t *event_out);
uint32_t gpio_hil_time(void);
uint16_t gpio_hil_epoch(void);
uint32_t gpio_fpga_version(void);

/* Helpers — read from AXI GPIO monitors */
int32_t  gpio_get_speed(void);
int32_t  gpio_get_ialpha(void);
int32_t  gpio_get_ibeta(void);
int32_t  gpio_get_flux_alpha(void);
int32_t  gpio_get_flux_beta(void);
int      gpio_get_data_valid(void);

#endif /* GPIO_H */
