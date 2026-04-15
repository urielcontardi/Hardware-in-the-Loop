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

static int   mem_fd = -1;

/* Each GPIO block is one page */
typedef struct {
    uint32_t base;
    volatile uint32_t *ptr;
} gpio_map_t;

static gpio_map_t maps[] = {
    { ADDR_GPIO_MONITOR_1,  NULL },
    { ADDR_GPIO_MONITOR_2,  NULL },
    { ADDR_GPIO_MONITOR_3,  NULL },
    { ADDR_GPIO_VDC_TORQUE, NULL },
    { ADDR_GPIO_VREF_AB,    NULL },
    { ADDR_GPIO_VREF_C,     NULL },
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
    if (mem_fd >= 0) {
        close(mem_fd);
        mem_fd = -1;
    }
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

/* ---------- helpers ---------- */

void gpio_set_vref(int32_t va, int32_t vb, int32_t vc)
{
    gpio_write(ADDR_GPIO_VREF_AB, GPIO_CH1_OFFSET, (uint32_t)va);
    gpio_write(ADDR_GPIO_VREF_AB, GPIO_CH2_OFFSET, (uint32_t)vb);
    gpio_write(ADDR_GPIO_VREF_C,  GPIO_CH1_OFFSET, (uint32_t)vc);
}

void gpio_set_pwm_ctrl(int enable, int clear_fault, uint32_t decim_ratio)
{
    uint32_t val = 0;
    if (enable)      val |= PWM_CTRL_ENABLE;
    if (clear_fault) val |= PWM_CTRL_CLEAR_FAULT;
    val |= (decim_ratio << PWM_CTRL_DECIM_SHIFT);
    gpio_write(ADDR_GPIO_VREF_C, GPIO_CH2_OFFSET, val);
}

void gpio_set_vdc_torque(int32_t vdc_q31, int32_t torque_q31)
{
    gpio_write(ADDR_GPIO_VDC_TORQUE, GPIO_CH1_OFFSET, (uint32_t)vdc_q31);
    gpio_write(ADDR_GPIO_VDC_TORQUE, GPIO_CH2_OFFSET, (uint32_t)torque_q31);
}

int32_t gpio_get_speed(void)      { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH1_OFFSET); }
int32_t gpio_get_ialpha(void)     { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH1_OFFSET); }
int32_t gpio_get_ibeta(void)      { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH2_OFFSET); }
int32_t gpio_get_flux_alpha(void) { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH1_OFFSET); }
int32_t gpio_get_flux_beta(void)  { return (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH2_OFFSET); }
int     gpio_get_data_valid(void) { return (int)gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH2_OFFSET); }
