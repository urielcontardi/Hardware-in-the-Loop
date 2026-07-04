# Sincronismo V/f–PWM por interrupção real (pico + vale da portadora)

**Date:** 2026-07-04
**Author:** Uriel Abe Contardi (with Claude)
**Status:** Approved for spec — aguardando revisão do usuário antes do plano de implementação

## Problema

O laço V/f do PS (`src/ps_app/main.c:84-99`, `vf_clock_thread`) atualiza
`va_ref/vb_ref/vc_ref` via uma *thread* de software livre
(`clock_nanosleep(CLOCK_MONOTONIC)` a `VF_TICK_HZ=1000` — `vf_ctrl.h:15`),
sem qualquer sincronismo com a portadora PWM de 1 kHz gerada no PL. O
`NPCModulator` amostra a referência uma vez por período da portadora, no
vale; como os dois relógios de 1 kHz são livres e independentes, a idade da
referência amostrada varia de forma não controlada (pior caso: batimento
1:1).

O hardware já tem a infraestrutura para eliminar isso — `carrier_tick_o` está
roteado para `IRQ_F2P[0]` do PS7 (`syn/hil/create_ebaz4205_project.tcl:607-616`)
— mas o software nunca consome essa interrupção. Este documento especifica a
mudança para que o PS reaja de fato à interrupção da portadora, escrevendo uma
nova referência a cada pico **e** vale (2× a taxa da portadora, travado em
fase).

## Escopo desta spec

Cobre: mudanças em VHDL (`Top_HIL.vhd`, `HIL_AXI_Top.vhd`), no método de
teste cocotb de L3, e no software do PS (`src/ps_app`), incluindo o nó de
device-tree necessário.

**Fora de escopo (etapa futura, explicitamente adiada):** ressíntese do
bitstream, rebuild/deploy do PetaLinux, reflash da EBAZ4205 e validação em
hardware real (L4). Nada aqui exige tocar na placa física.

## Motor de referência (nota lateral, já corrigido separadamente)

Rs/J do motor usado em toda a cadeia foram corrigidos em paralelo a este
trabalho (commit `e0e6907`, motor real "LVP 760V" ~22 kW,
`extras/induction-motor-model/psim/1_modelValidation/paramSim.txt`). Não é
parte desta spec, mas os testes cocotb descritos aqui devem herdar os
defaults já corrigidos de `verification/cocotb/run.py` sem overrides manuais.

## Design

### 1. VHDL — habilitar amostragem em pico+vale

O `NPCModulator.vhd` já implementa amostragem em pico+vale via o generic
`LOAD_BOTH_EDGES` (hoje `false` em todo lugar) e já expõe `sample_tick_o <=
valley or peak when LOAD_BOTH_EDGES else valley`. O `NPCManager.vhd`
(wrapper que instancia o modulador) já repassa `LOAD_BOTH_EDGES` e
`sample_tick_o` corretamente. Nenhuma mudança é necessária nesses dois
arquivos — só nos dois tops:

**`Top_HIL.vhd`** (simulação): já expõe `sample_tick_o` no próprio topo,
already wired (`sample_tick_o => sample_tick_o`, linha 254). Única mudança:

```vhdl
-- linha 235
LOAD_BOTH_EDGES  => true,   -- era false
```

**`HIL_AXI_Top.vhd`** (hardware real): `sample_tick_o` do `NPCManager_Inst`
está desconectado (`sample_tick_o => open`, linha ~465) e a porta de topo
`carrier_tick_o` (a que alimenta `IRQ_F2P` de verdade) é alimentada por
`carrier_tick_s`, que é só-vale. Mudanças:

```vhdl
-- generic map do NPCManager_Inst
LOAD_BOTH_EDGES => true,   -- era false

-- port map do NPCManager_Inst
sample_tick_o => vf_irq_tick_s,   -- era "open"; vf_irq_tick_s é sinal novo

-- atribuição da porta de topo (hoje ~linha 424: carrier_tick_o <= carrier_tick_s;)
carrier_tick_o <= vf_irq_tick_s;  -- era carrier_tick_s
```

O contador de diagnóstico `carrier_tick_ctr` continua alimentado por
`carrier_tick_s` (inalterado — `NPCManager`'s próprio `carrier_tick_o` nunca
muda de semântica, é sempre só-vale). Isso preserva "1 pulso = 1 período da
portadora" nesse contador, mesmo com a IRQ real agora pulsando 2×/período.
Como o nome e a fiação da porta `carrier_tick_o` no bloco de IP não mudam
(só a lógica interna que a alimenta), **nenhuma alteração no block
design/.tcl é necessária** — só ressíntese, quando chegar a hora.

### 2. cocotb — novo método canônico de teste L3

Isso é uma **mudança de método**, não uma opção adicional: o modelo Python
que hoje simula o "PS" nos testes L3 escrevendo referências num relógio
livre (`VF_TICK_TS=0.001` fixo em `verification/cocotb/scripts/fpga_vs_c.py`
e a lógica equivalente usada por `tests/test_top_hil.py`) passa a
`await RisingEdge(dut.sample_tick_o)` antes de cada escrita, em vez de
dormir um período fixo. Isso é o único método de daqui pra frente — o
modelo livre não é mantido como opção.

Detalhe de inicialização: precisa de uma escrita "de partida" antes da
primeira borda (espelhando `main.c:117`, que chama `vf_tick()` uma vez antes
de armar o relógio), senão o primeiro meio-período fica com referência
zerada.

**Consequência:** todo resultado L3 já existente (`l3_top_pwm_replay_*`,
`l3_fullstack_*`, o L3 de A1/A2) foi gerado com o método livre e fica
metodologicamente obsoleto — precisa reexecutar depois que este trabalho
estiver implementado, empilhado sobre a rerodada de Rs/J já pendente.

### 3. Software do PS — consumir a IRQ de verdade

**Novo módulo `src/ps_app/vf_irq.c` / `vf_irq.h`:** abre o `/dev/uioN`
correspondente (descoberto por nome via `/sys/class/uio/uioX/name`, não por
número fixo — número de UIO pode variar entre boots), e substitui o corpo de
`vf_clock_thread` (`main.c:84-99`) por um laço bloqueante:

```c
for (;;) {
    uint32_t count;
    if (read(uio_fd, &count, sizeof(count)) != sizeof(count)) break;
    if (!vf_clock_active) break;
    vf_tick();
    uint32_t reenable = 1;
    write(uio_fd, &reenable, sizeof(reenable));  // re-arma a IRQ (contrato UIO)
}
```

A estrutura em volta (`setup_vf_timer`/`cancel_timer`, prime de `vf_tick()`
antes de armar, serialização com `tick_mutex`) permanece igual — só o
mecanismo de espera muda de `clock_nanosleep` para `read()` bloqueante.

**`VF_TICK_HZ` precisa dobrar** (`vf_ctrl.h:15`, `1000u` → `2000u`): com a
IRQ disparando no pico *e* no vale da portadora de 1 kHz, `vf_tick()` passa a
ser chamado a 2 kHz. Como `TS = 1/VF_TICK_HZ` (`vf_ctrl.c:12`) é o passo de
integração do ângulo elétrico (`theta += omega*TS`), não ajustar isso faria
o ângulo avançar no dobro da velocidade real.

**Device-tree:** nó UIO genérico (`compatible = "generic-uio"` ou
`"linux,uio_pdrv_genirq"`), rotulado `label = "vf_irq"` — esse é o nome que
`vf_irq.c` procura em `/sys/class/uio/uioX/name`, evitando depender do índice
`uioN`, que pode variar entre boots. Nó adicionado em
`syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`.
Convenção Zynq-7000: F2P[0] mapeia para SPI 61 do GIC, codificado em
devicetree como `interrupts = <0 29 4>;` (29 = 61−32, offset padrão de SPI) —
**confirmar esse número contra o endereço/IRQ real do bloco de IP durante a
implementação**, não assumir cego. Esse nó só produz efeito depois de um
rebuild do PetaLinux (bitbake) — não faz nada até lá, e não é acionado por
este trabalho.

## Testes

- `tb_NPCModulator.vhd` já cobre `LOAD_BOTH_EDGES=true` isoladamente — não
  precisa de teste novo nesse nível.
- Novo teste cocotb (extensão de `tests/test_top_hil.py`), rodando o mesmo
  estímulo V/f já usado em `S0`/`A1` (0–2 s, `f_nominal=60Hz`,
  `acc_ramp=60Hz/s`), validando: (a) `sample_tick_o` pulsa 2×/período da
  portadora; (b) o modelo C recebe uma escrita por borda; (c) métricas
  NRMSE/MAE no formato `metrics.json` já usado, sem comparação lado-a-lado
  com o método livre.
- Software do PS: sem hardware real disponível agora, `vf_irq.c` é
  revisável/compilável mas não testável end-to-end nesta etapa — isso fica
  para a validação em hardware (fora de escopo, adiada).

## Riscos / itens em aberto

- Número exato da IRQ no device-tree (29 vs outro) precisa confirmação
  durante a implementação, não é definitivo aqui. Nome do nó (`vf_irq`) já
  está decidido nesta spec.
- Nenhuma validação em hardware real ocorre neste trabalho; a lacuna entre
  "código pronto" e "código testado em silício" fica aberta até a etapa
  futura explicitamente adiada.
