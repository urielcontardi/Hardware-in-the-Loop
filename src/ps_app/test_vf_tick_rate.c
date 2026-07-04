/* Teste standalone (sem hardware) do passo de integracao angular do V/F.
 * Nao chama vf_tick() (depende de mmap real) — replica so a formula de
 * theta += omega*TS usada em vf_ctrl.c, para garantir que TS acompanha a
 * taxa real de chamada da IRQ (2x a portadora, pico+vale). */
#include <stdio.h>
#include <math.h>
#include "vf_ctrl.h"

int main(void)
{
    /* Em 60 Hz, uma volta completa (2*pi rad) deve levar exatamente 1/60 s.
     * Com a IRQ disparando a VF_TICK_HZ (pico+vale), o numero de ticks para
     * uma volta completa deve ser VF_TICK_HZ / 60. */
    const float freq_hz = 60.0f;
    const float ts = 1.0f / (float)VF_TICK_HZ;
    const float omega = 2.0f * (float)M_PI * freq_hz;
    float theta = 0.0f;
    int ticks = 0;
    while (theta < 2.0f * (float)M_PI) {
        theta += omega * ts;
        ticks++;
    }
    /* O loop de acumulacao sempre "estoura" para o proximo inteiro (para na
     * primeira vez que theta >= 2*pi), entao o numero de ticks esperado e'
     * o teto da divisao exata, nao o arredondamento pro mais proximo. */
    int expected_ticks = (int)ceilf((float)VF_TICK_HZ / freq_hz);
    printf("VF_TICK_HZ=%u ticks_por_volta=%d esperado=%d\n",
           VF_TICK_HZ, ticks, expected_ticks);
    if (ticks != expected_ticks) {
        fprintf(stderr, "FALHOU: esperava %d ticks/volta, obteve %d\n",
                expected_ticks, ticks);
        return 1;
    }
    if (VF_TICK_HZ != 2000u) {
        fprintf(stderr, "FALHOU: VF_TICK_HZ deveria ser 2000 (pico+vale a 1kHz), e' %u\n",
                VF_TICK_HZ);
        return 1;
    }
    printf("OK\n");
    return 0;
}
