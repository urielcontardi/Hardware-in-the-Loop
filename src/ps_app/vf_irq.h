#ifndef VF_IRQ_H
#define VF_IRQ_H

/*
 * Consome a interrupcao real da portadora (carrier_tick_o -> IRQ_F2P do PS7,
 * exposta como /dev/uioX pelo no de device-tree rotulado "vf_irq") e chama
 * vf_tick() a cada borda (pico+vale, 2x/periodo da portadora). Substitui a
 * thread de clock_nanosleep livre que existia antes deste trabalho — ver
 * docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md.
 *
 * Sem hardware real (placa nao ligada ou no de device-tree ausente),
 * vf_irq_start() falha e retorna -1; quem chama decide o que fazer
 * (o daemon nao tem fallback de software livre — essa e' a decisao
 * explicita deste trabalho, nao um bug).
 */

int  vf_irq_start(void);   /* abre /dev/uioX (por label "vf_irq") e sobe a thread */
void vf_irq_stop(void);    /* para a thread e fecha o fd */

#endif /* VF_IRQ_H */
