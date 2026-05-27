#include "gpio.h"

#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>
#include <string.h>

#define PAGE_SIZE  4096UL
#define PAGE_MASK  (~(PAGE_SIZE - 1))

static int mem_fd = -1;

typedef struct {
    uint32_t base;
    volatile uint32_t *ptr;
} map_t;

static map_t maps[] = {
    /* Monitor GPIOs (read) */
    { ADDR_GPIO_MONITOR_1, NULL },
    { ADDR_GPIO_MONITOR_2, NULL },
    { ADDR_GPIO_MONITOR_3, NULL },
    /* HIL_Regs_AXI custom slave (write) */
    { ADDR_HIL_REGS,       NULL },
};
#define N_MAPS (sizeof(maps) / sizeof(maps[0]))

static volatile uint32_t *map_addr(uint32_t base)
{
    for (size_t i = 0; i < N_MAPS; i++)
        if (maps[i].base == base)
            return maps[i].ptr;
    return NULL;
}

int gpio_init(void)
{
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        fprintf(stderr, "gpio_init: open /dev/mem: %s\n", strerror(errno));
        return -1;
    }
    for (size_t i = 0; i < N_MAPS; i++) {
        void *p = mmap(NULL, PAGE_SIZE, PROT_READ | PROT_WRITE,
                       MAP_SHARED, mem_fd, maps[i].base & PAGE_MASK);
        if (p == MAP_FAILED) {
            fprintf(stderr, "gpio_init: mmap 0x%08x: %s\n",
                    maps[i].base, strerror(errno));
            gpio_deinit();
            return -1;
        }
        maps[i].ptr = (volatile uint32_t *)p;
    }
    return 0;
}

void gpio_deinit(void)
{
    for (size_t i = 0; i < N_MAPS; i++) {
        if (maps[i].ptr) {
            munmap((void *)maps[i].ptr, PAGE_SIZE);
            maps[i].ptr = NULL;
        }
    }
    if (mem_fd >= 0) { close(mem_fd); mem_fd = -1; }
}

void gpio_write(uint32_t base, uint32_t offset, uint32_t val)
{
    volatile uint32_t *p = map_addr(base);
    if (p) p[offset / 4] = val;
}

uint32_t gpio_read(uint32_t base, uint32_t offset)
{
    volatile uint32_t *p = map_addr(base);
    return p ? p[offset / 4] : 0;
}

/* ── Writes to HIL_Regs_AXI ──────────────────────────────────────────── */

void gpio_set_vref(int32_t va, int32_t vb, int32_t vc)
{
    gpio_write(ADDR_HIL_REGS, REG_VA_REF, (uint32_t)va);
    gpio_write(ADDR_HIL_REGS, REG_VB_REF, (uint32_t)vb);
    gpio_write(ADDR_HIL_REGS, REG_VC_REF, (uint32_t)vc);
}

void gpio_set_pwm_ctrl(int enable, int clear_fault, int solver_reset,
                       uint32_t decim_ratio)
{
    uint32_t val = 0;
    if (enable)       val |= PWM_CTRL_ENABLE;
    if (clear_fault)  val |= PWM_CTRL_CLEAR_FAULT;
    if (solver_reset) val |= PWM_CTRL_SOLVER_RESET;
    val |= (decim_ratio << PWM_CTRL_DECIM_SHIFT);
    gpio_write(ADDR_HIL_REGS, REG_PWM_CTRL, val);
}

void gpio_set_vdc_torque(int32_t vdc_word, int32_t torque_word)
{
    gpio_write(ADDR_HIL_REGS, REG_VDC_WORD,    (uint32_t)vdc_word);
    gpio_write(ADDR_HIL_REGS, REG_TORQUE_WORD, (uint32_t)torque_word);
}

void gpio_write_tim_coeff(uint32_t matrix, uint32_t row, uint32_t col,
                          int64_t coeff_q14_28)
{
    uint64_t raw = (uint64_t)coeff_q14_28 & ((1ULL << 42) - 1ULL);
    gpio_write(ADDR_HIL_REGS, REG_COEFF_ADDR, TIM_COEFF_ADDR(matrix, row, col));
    gpio_write(ADDR_HIL_REGS, REG_COEFF_DATA_LO, (uint32_t)(raw & 0xffffffffULL));
    gpio_write(ADDR_HIL_REGS, REG_COEFF_DATA_HI, (uint32_t)(raw >> 32));
    gpio_write(ADDR_HIL_REGS, REG_COEFF_COMMIT, TIM_COEFF_WRITE_STROBE);
}

void gpio_apply_tim_coeffs(void)
{
    gpio_write(ADDR_HIL_REGS, REG_COEFF_COMMIT, TIM_COEFF_APPLY_STROBE);
}

/* ── PWM event capture readout ──────────────────────────────────────── */

void gpio_pwmcap_clear(void)
{
    gpio_write(ADDR_HIL_REGS, REG_PWM_CAP_CTRL, PWM_CAP_CTRL_CLEAR);
}

void gpio_pwmcap_start(void)
{
    gpio_write(ADDR_HIL_REGS, REG_PWM_CAP_CTRL, PWM_CAP_CTRL_START);
}

void gpio_pwmcap_stop(void)
{
    gpio_write(ADDR_HIL_REGS, REG_PWM_CAP_CTRL, PWM_CAP_CTRL_STOP);
}

void gpio_pwmcap_set_window(uint32_t cycles)
{
    gpio_write(ADDR_HIL_REGS, REG_PWM_CAP_WINDOW, cycles);
}

uint32_t gpio_pwmcap_status(void)
{
    return gpio_read(ADDR_HIL_REGS, REG_PWM_CAP_STATUS);
}

uint16_t gpio_pwmcap_count(void)
{
    return (uint16_t)(gpio_pwmcap_status() >> 16);
}

uint64_t gpio_pwmcap_peek(void)
{
    uint32_t lo = gpio_read(ADDR_HIL_REGS, REG_PWM_CAP_DATA_LO);
    uint32_t hi = gpio_read(ADDR_HIL_REGS, REG_PWM_CAP_DATA_HI);
    return ((uint64_t)hi << 32) | lo;
}

void gpio_pwmcap_pop(void)
{
    gpio_write(ADDR_HIL_REGS, REG_PWM_CAP_POP, 1U);
}

int gpio_pwmcap_read(uint64_t *event_out)
{
    if (!event_out) return 0;
    if (gpio_pwmcap_status() & PWM_CAP_STATUS_EMPTY) return 0;
    *event_out = gpio_pwmcap_peek();
    gpio_pwmcap_pop();
    return 1;
}

uint32_t gpio_hil_time(void)
{
    return gpio_read(ADDR_HIL_REGS, REG_HIL_TIME);
}

uint16_t gpio_hil_epoch(void)
{
    return (uint16_t)(gpio_read(ADDR_HIL_REGS, REG_HIL_EPOCH) & 0xffffU);
}

/* ── Reads from AXI GPIO monitors ────────────────────────────────────── */

int32_t gpio_get_speed(void)      { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH1_OFFSET); }
int32_t gpio_get_ialpha(void)     { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH1_OFFSET); }
int32_t gpio_get_ibeta(void)      { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH2_OFFSET); }
int32_t gpio_get_flux_alpha(void) { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH1_OFFSET); }
int32_t gpio_get_flux_beta(void)  { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH2_OFFSET); }
int     gpio_get_data_valid(void) { return (int)gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH2_OFFSET); }
