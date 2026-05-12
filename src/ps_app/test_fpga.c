/*
 * test_fpga.c — Smoke test isolado para verificar cada camada do HIL PL.
 *
 * Execução no board:
 *   sudo ./test_fpga
 *
 * O programa testa em ordem:
 *   1. AXI bus: escreve um padrão em HIL_Regs_AXI e lê de volta
 *   2. TIM_Solver: força tensão DC constante + enable, lê monitores de debug
 *   3. Relatório: imprime contadores internos do PL
 *
 * Interpretação:
 *   STEP 1 FAIL → FPGA não configurado ou endereço HIL_Regs_AXI errado
 *   STEP 2 free_run parado → clock/reset do HIL_AXI_Top
 *   STEP 2 carrier parado  → NPCManager/carrier/reset
 *   STEP 2 timer parado    → timer do TIM_Solver/generic Ts
 *   STEP 2 timer ok, done parado/busy preso → BilinearSolverHandler/DSP
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

#include "gpio.h"

/* Escala Q18.14 para o PS escrever Vdc/torque */
#define PS_FRAC_SCALE  ((float)(1 << 14))

static void ms_sleep(int ms)
{
    struct timespec ts = { .tv_sec = ms / 1000,
                           .tv_nsec = (long)(ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

/* ─────────────────────────────────────────────────────────────────────── */

/* AXI GPIO: offsets dos registradores de direção (TRI) */
#define GPIO_TRI1_OFFSET   0x004U
#define GPIO_TRI2_OFFSET   0x00CU

static void test_gpio_map(void)
{
    printf("\n=== STEP 0: Verificacao dos enderecos AXI GPIO ===\n");
    printf("  (TRI=0xFFFFFFFF confirma GPIO input-only configurado corretamente)\n\n");

    struct { uint32_t base; const char *name; int ch2_bits; } gpios[] = {
        { ADDR_GPIO_MONITOR_1, "Monitor1 (ialpha/ibeta)",      32 },
        { ADDR_GPIO_MONITOR_2, "Monitor2 (flux_a/flux_b)",     32 },
        { ADDR_GPIO_MONITOR_3, "Monitor3 (speed/data_valid)",   1 },
    };

    for (size_t i = 0; i < sizeof(gpios)/sizeof(gpios[0]); i++) {
        uint32_t tri1 = gpio_read(gpios[i].base, GPIO_TRI1_OFFSET);
        uint32_t tri2 = gpio_read(gpios[i].base, GPIO_TRI2_OFFSET);
        uint32_t expected2 = (gpios[i].ch2_bits == 1) ? 0x00000001U : 0xFFFFFFFFU;
        printf("  @ 0x%08X  %s\n", gpios[i].base, gpios[i].name);
        printf("    TRI_ch1=0x%08X %s  TRI_ch2=0x%08X %s\n",
               tri1, tri1 == 0xFFFFFFFFU ? "OK" : "FAIL",
               tri2, tri2 == expected2 ? "OK" : "FAIL");
    }
}

/* ─────────────────────────────────────────────────────────────────────── */

static int test_axi_readback(void)
{
    printf("\n=== STEP 1: AXI bus readback (HIL_Regs_AXI @ 0x%08X) ===\n",
           ADDR_HIL_REGS);

    const uint32_t patterns[] = { 0x12345678U, 0xDEADBEEFU, 0x00000000U, 0xFFFFFFFFU };
    int ok = 1;

    for (size_t i = 0; i < sizeof(patterns)/sizeof(patterns[0]); i++) {
        uint32_t wr = patterns[i];
        gpio_write(ADDR_HIL_REGS, REG_VA_REF, wr);
        uint32_t rd = gpio_read(ADDR_HIL_REGS, REG_VA_REF);
        int pass = (rd == wr);
        printf("  write=0x%08X  read=0x%08X  %s\n", wr, rd, pass ? "OK" : "FAIL");
        if (!pass) ok = 0;
    }

    gpio_write(ADDR_HIL_REGS, REG_VA_REF, 0);

    /* Verifica magic read-only em 0x18 — prova que o bitstream é desta build */
    uint32_t regs_magic = gpio_read(ADDR_HIL_REGS, REG_DEBUG_MAGIC);
    printf("\n  Verificacao do bitstream (0x18 = DEBUG_MAGIC):\n");
    printf("    regs_magic = 0x%08X  %s\n",
           regs_magic, regs_magic == 0x48494C52U ? "OK" : "FAIL");

    if (regs_magic != 0x48494C52U) {
        printf("  [!] Bitstream desatualizado ou FPGA nao configurado.\n"
               "      Rode: sudo fpgautil -b ebaz4205_wrapper.bin\n");
        ok = 0;
    }

    if (ok)
        printf("  RESULTADO: PASS — AXI bus funcionando\n");
    else
        printf("  RESULTADO: FAIL — FPGA nao configurado ou endereco errado!\n"
               "             Verifique se o bitstream foi carregado.\n");
    return ok ? 0 : -1;
}

static void print_debug_status(uint32_t status)
{
    printf("    status=0x%08X\n", status);
    printf("      rst_n=%u enable=%u clear=%u carrier_pulse=%u timer_pulse=%u clarke_valid=%u\n",
           (status >> 0) & 1U, (status >> 1) & 1U, (status >> 2) & 1U,
           (status >> 3) & 1U, (status >> 4) & 1U, (status >> 5) & 1U);
    printf("      solver_busy=%u solver_done=%u data_valid=%u data_valid_latch=%u tready=%u tvalid=%u\n",
           (status >> 6) & 1U, (status >> 7) & 1U, (status >> 8) & 1U,
           (status >> 9) & 1U, (status >> 10) & 1U, (status >> 11) & 1U);
    printf("      pwm_a=0x%X pwm_b=0x%X pwm_c=0x%X pwm_ctrl_lsb=0x%02X\n",
           (status >> 12) & 0xFU, (status >> 16) & 0xFU,
           (status >> 20) & 0xFU, (status >> 24) & 0xFFU);
}

static void read_debug_monitors(uint32_t *free_run,
                                uint32_t *carrier,
                                uint32_t *timer,
                                uint32_t *solver_done,
                                uint32_t *status,
                                uint32_t *data_valid_latch)
{
    /* Debug bus agora vem do HIL_Regs_AXI (offsets 0x1C..0x2C).
     * Os AXI GPIO monitors carregam grandezas físicas reais. */
    *status           = gpio_read(ADDR_HIL_REGS, REG_DEBUG_STATUS);
    *free_run         = gpio_read(ADDR_HIL_REGS, REG_DEBUG_FREE_RUN);
    *carrier          = gpio_read(ADDR_HIL_REGS, REG_DEBUG_CARRIER);
    *timer            = gpio_read(ADDR_HIL_REGS, REG_DEBUG_TIMER);
    *data_valid_latch = gpio_read(ADDR_HIL_REGS, REG_DEBUG_DV_LATCH) & 1U;
    *solver_done      = 0;
}

static void read_physical_monitors(int32_t *ialpha,
                                   int32_t *ibeta,
                                   int32_t *flux_a,
                                   int32_t *flux_b,
                                   int32_t *speed,
                                   uint32_t *data_valid)
{
    *ialpha     = (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH1_OFFSET);
    *ibeta      = (int32_t)gpio_read(ADDR_GPIO_MONITOR_1, GPIO_CH2_OFFSET);
    *flux_a     = (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH1_OFFSET);
    *flux_b     = (int32_t)gpio_read(ADDR_GPIO_MONITOR_2, GPIO_CH2_OFFSET);
    *speed      = (int32_t)gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH1_OFFSET);
    *data_valid = gpio_read(ADDR_GPIO_MONITOR_3, GPIO_CH2_OFFSET) & 1U;
}

static void print_debug_snapshot(const char *tag)
{
    uint32_t free_run, carrier, timer, solver_done, status, dv_latch;

    read_debug_monitors(&free_run, &carrier, &timer, &solver_done, &status, &dv_latch);
    printf("\n  Debug monitors (%s):\n", tag);
    printf("    free_run_ctr     = %10u\n", free_run);
    printf("    carrier_tick_ctr = %10u\n", carrier);
    printf("    timer_tick_ctr   = %10u\n", timer);
    printf("    data_valid_latch = %10u\n", dv_latch);
    print_debug_status(status);
}

static int test_solver(void)
{
    printf("\n=== STEP 2: Debug interno do HIL/TIM_Solver ===\n");

    const float   vdc_v = 100.0f;
    const int32_t vdc_q = (int32_t)(vdc_v * PS_FRAC_SCALE);
    const int32_t va    =  CARRIER_MAX / 2;
    const int32_t vb    = -CARRIER_MAX / 2;
    const int32_t vc    =  0;

    printf("  Configurando: Vdc=%.0fV  va=%d  vb=%d  vc=%d  enable=1\n",
           vdc_v, va, vb, vc);

    print_debug_snapshot("antes da configuracao");

    gpio_set_vdc_torque(vdc_q, 0);
    gpio_set_vref(va, vb, vc);
    gpio_set_pwm_ctrl(0, 1, 0, 0);   /* clear_fault */
    ms_sleep(2);
    print_debug_snapshot("apos clear_fault");

    gpio_set_pwm_ctrl(1, 0, 0, 0);   /* enable */

    uint32_t free0, carrier0, timer0, done0, status0, dv0;
    uint32_t free1, carrier1, timer1, done1, status1, dv1;

    read_debug_monitors(&free0, &carrier0, &timer0, &done0, &status0, &dv0);
    (void)status0;
    (void)dv0;
    (void)done0;
    printf("\n  Aguardando 1000 ms para medir deltas...\n");
    ms_sleep(1000);
    read_debug_monitors(&free1, &carrier1, &timer1, &done1, &status1, &dv1);
    (void)done1;

    printf("\n  Debug monitors (apos enable):\n");
    printf("    free_run_ctr     = %10u  delta=%10u\n", free1,    free1 - free0);
    printf("    carrier_tick_ctr = %10u  delta=%10u\n", carrier1, carrier1 - carrier0);
    printf("    timer_tick_ctr   = %10u  delta=%10u\n", timer1,   timer1 - timer0);
    printf("    data_valid_latch = %10u\n", dv1);
    print_debug_status(status1);

    printf("\n  Diagnostico:\n");

    if (free1 == free0) {
        printf("  [!] HIL_AXI_Top nao tem clock: free_run_ctr nao incrementa.\n");
        return -1;
    }

    if (((status1 >> 0) & 1U) == 0U) {
        printf("  [!] Clock do HIL_AXI_Top esta vivo, mas rst_n esta baixo.\n"
               "      Foque no reset vindo de proc_sys_reset_0/peripheral_aresetn.\n");
        return -1;
    }

    if (carrier1 == carrier0) {
        printf("  [!] Clock/reset do top OK, mas carrier_tick nao incrementa.\n"
               "      Foque no NPCManager/parametros CLK_FREQ/PWM_FREQ/reset.\n");
        return -1;
    }

    if (timer1 == timer0) {
        printf("  [!] NPC roda, mas timer_tick do TIM_Solver nao incrementa.\n"
               "      Foque no generic Ts/CLOCK_FREQUENCY ou sintese do timer.\n");
        return -1;
    }

    if (dv1 == 0U) {
        printf("  [!] Timer do TIM_Solver roda, mas data_valid nao aparece.\n"
               "      Se solver_busy=1, o BilinearSolverHandler ficou preso.\n"
               "      Se solver_busy=0, o start/clarke_valid nao esta iniciando o handler.\n");
        return -1;
    }

    printf("  [OK] Caminho clock/reset/timer/solver_done esta vivo.\n");
    return 0;
}

/* ─────────────────────────────────────────────────────────────────────── */

/* Q14.28 → physical: o AXI GPIO entrega os 32 MSBs de um valor de 42 bits
 * em Q14.28, então o valor lido é Q14.18 → divisor = 2^18 = 262144. */
static double q1418_to_real(int32_t q)
{
    return (double)q / 262144.0;
}

static int test_physical(void)
{
    printf("\n=== STEP 3: Grandezas fisicas (AXI GPIO monitors) ===\n");

    int32_t  ialpha, ibeta, flux_a, flux_b, speed;
    uint32_t dv;

    /* Lê 3x com pequeno intervalo para confirmar atividade */
    for (int i = 0; i < 3; i++) {
        read_physical_monitors(&ialpha, &ibeta, &flux_a, &flux_b, &speed, &dv);
        printf("\n  Amostra %d (data_valid=%u):\n", i + 1, dv);
        printf("    ialpha     = %12d  (%9.4f A)\n",  ialpha, q1418_to_real(ialpha));
        printf("    ibeta      = %12d  (%9.4f A)\n",  ibeta,  q1418_to_real(ibeta));
        printf("    flux_alpha = %12d  (%9.4f Wb)\n", flux_a, q1418_to_real(flux_a));
        printf("    flux_beta  = %12d  (%9.4f Wb)\n", flux_b, q1418_to_real(flux_b));
        printf("    speed_mech = %12d  (%9.4f rad/s)\n", speed, q1418_to_real(speed));
        ms_sleep(100);
    }

    if (dv == 0) {
        printf("\n  [!] data_valid=0 — solver nao produziu saida.\n");
        return -1;
    }

    printf("\n  [OK] Solver gerando grandezas fisicas via AXI GPIO.\n");
    return 0;
}

/* ─────────────────────────────────────────────────────────────────────── */

int main(void)
{
    printf("HIL FPGA Smoke Test\n");
    printf("===================\n");

    if (gpio_init() < 0) {
        fprintf(stderr, "Falha ao mapear /dev/mem. Rode com sudo.\n");
        return 1;
    }

    test_gpio_map();

    int step1 = test_axi_readback();
    if (step1 < 0) {
        printf("\nAbortando: AXI bus nao responde.\n");
        gpio_deinit();
        return 1;
    }

    int step2 = test_solver();
    int step3 = test_physical();

    /* Desliga o modulador antes de sair */
    gpio_set_pwm_ctrl(0, 0, 0, 0);
    gpio_set_vref(0, 0, 0);
    gpio_set_vdc_torque(0, 0);
    gpio_deinit();

    printf("\n=== RESUMO ===\n");
    printf("  AXI bus (HIL_Regs readback): %s\n", step1 == 0 ? "OK" : "FAIL");
    printf("  TIM_Solver debug counters:   %s\n", step2 == 0 ? "OK" : "FAIL");
    printf("  Grandezas fisicas no GPIO:   %s\n", step3 == 0 ? "OK" : "FAIL");
    printf("\n");

    return (step1 == 0 && step2 == 0 && step3 == 0) ? 0 : 1;
}
