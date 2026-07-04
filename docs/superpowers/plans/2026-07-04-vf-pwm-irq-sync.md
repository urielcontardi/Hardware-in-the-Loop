# Sincronismo V/f-PWM por Interrupção Real (Pico+Vale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o PS reagir de verdade à interrupção real da portadora PWM
(pico+vale, 2×/período) em vez do relógio de software livre atual, eliminando
o jitter de fase entre a referência V/f e a modulação.

**Architecture:** `NPCModulator`/`NPCManager` já implementam amostragem em
pico+vale via o generic `LOAD_BOTH_EDGES` (hoje desligado); habilitamos isso
nos dois tops (`Top_HIL.vhd` para simulação, `HIL_AXI_Top.vhd` para hardware
real), criamos o novo método canônico de teste cocotb L3 travado nessa tick, e
reescrevemos o laço V/f do PS (`src/ps_app`) para consumir a IRQ real via UIO
em vez de `clock_nanosleep`.

**Tech Stack:** VHDL (GHDL/NVC via cocotb, Vivado para syntax-check do top
real), Python/cocotb, C (daemon do PS, cross-compilado para ARM Cortex-A9),
device-tree (PetaLinux).

## Global Constraints

- Especificado em `docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md` — qualquer dúvida de escopo, essa é a fonte.
- Ressíntese do bitstream, rebuild do PetaLinux, reflash da EBAZ4205 e validação em hardware real (L4) estão **fora de escopo** deste plano — nenhuma task aciona isso.
- `carrier_tick_ctr` (registrador de diagnóstico `0x24`, contador só-vale) não pode mudar de significado — continua contando 1 pulso/período da portadora em todo lugar.
- Motor de referência já corrigido separadamente (commit `e0e6907`, Rs=0.4396/J=0.4) — as tasks de teste devem usar os defaults já corrigidos de `verification/cocotb/run.py` sem overrides manuais de `IM_RS`/`IM_J`.
- Nome do nó de device-tree/label UIO é `vf_irq` (decidido na spec) — não inventar outro nome.

---

## Task 1: VHDL — `Top_HIL.vhd` amostra em pico+vale

**Files:**
- Modify: `src/rtl/Top_HIL.vhd:235`
- Test: `verification/cocotb/tests/test_top_hil.py` (novo teste, inserir antes da linha 363)

**Interfaces:**
- Consumes: porta já existente `Top_HIL.sample_tick_o` (linha 112, já conectada internamente ao `NPCManager` na linha 254 — nada a mudar na fiação, só o generic).
- Produces: `sample_tick_o` agora pulsa 2×/período da portadora quando `pwm_enb_i=1`. Task 3 depende deste comportamento.

- [ ] **Step 1: Escrever o teste que falha**

Inserir em `verification/cocotb/tests/test_top_hil.py`, imediatamente antes da
linha `363: async def test_top_hil_pwm_replay_l3(dut):` (mesma indentação/
padrão dos testes acima, com o decorator `@cocotb.test()`):

```python
# ═══════════════════════════════════════════════════════════════════════
#  TEST: sample_tick_o pulsa em pico E vale (LOAD_BOTH_EDGES)
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_top_hil_carrier_dual_edge(dut):
    """LOAD_BOTH_EDGES=true deve fazer sample_tick_o pulsar 2x por periodo da
    portadora (pico e vale), nao 1x. Guarda de regressao para a mudanca em
    docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md."""
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.pwm_enb_i.value = 1

    carrier_period_cycles = CLK_FREQ // PWM_FREQ  # 5000 ciclos a 100MHz/20kHz
    n_periods = 10

    tick_count = 0

    async def counter():
        nonlocal tick_count
        while True:
            await RisingEdge(dut.sample_tick_o)
            tick_count += 1

    cocotb.start_soon(counter())
    await ClockCycles(dut.clk_i, carrier_period_cycles * n_periods)

    assert tick_count == 2 * n_periods, (
        f"esperava {2 * n_periods} pulsos de sample_tick_o em {n_periods} "
        f"periodos da portadora (pico+vale), contei {tick_count}"
    )
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd verification/cocotb
uv run python run.py --sim nvc --top top_hil --test top_hil -k test_top_hil_carrier_dual_edge
```

Esperado: FAIL, `tick_count == 10` (só o vale pulsa hoje), não `20`.

- [ ] **Step 3: Aplicar a mudança mínima**

Em `src/rtl/Top_HIL.vhd`, linha 235 (dentro do `generic map` do
`NPCManager_Inst`):

```vhdl
        LOAD_BOTH_EDGES  => true,           -- era false
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd verification/cocotb
uv run python run.py --sim nvc --top top_hil --test top_hil -k test_top_hil_carrier_dual_edge
```

Esperado: PASS, `tick_count == 20`.

- [ ] **Step 5: Commit**

```bash
git add src/rtl/Top_HIL.vhd verification/cocotb/tests/test_top_hil.py
git commit -m "feat(rtl): habilita amostragem pico+vale (LOAD_BOTH_EDGES) no Top_HIL.vhd"
```

---

## Task 2: VHDL — `HIL_AXI_Top.vhd` religa a IRQ real para pico+vale

**Files:**
- Modify: `src/rtl/HIL_AXI_Top.vhd:190` (declaração de sinal), `:429` (atribuição da porta de topo), `:464` (generic map), `:479` (port map)
- Test: script Vivado `check_syntax` (novo arquivo `syn/hil/check_hil_axi_top_syntax.tcl`)

**Interfaces:**
- Consumes: nenhuma dependência de outra task.
- Produces: porta de topo `carrier_tick_o` (a que alimenta `IRQ_F2P` de verdade, fiação inalterada no block design) passa a pulsar 2×/período. `carrier_tick_ctr` (diagnóstico) continua só-vale.

- [ ] **Step 1: Confirmar o estado atual com o syntax-check (deve passar mesmo antes da mudança)**

Criar `syn/hil/check_hil_axi_top_syntax.tcl`:

```tcl
# Syntax-check standalone do HIL_AXI_Top.vhd e dependencias, sem criar um
# projeto Vivado completo nem sintetizar. Usado como teste rapido de
# elaboracao — nao substitui a sintese real (fora de escopo deste plano).
set root_dir "/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop"
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverPkg.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/HIL_Regs_AXI.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverUnit.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/bilinear_solver/src/BilinearSolverHandler.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/clarke_transform/src/ClarkeTransform.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/edge_detector/src/EdgeDetector.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCModulator.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCGateDriver.vhd
read_vhdl -vhdl2008 $root_dir/common/modules/npc_modulator/src/NPCManager.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/TIM_Solver.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/IIRFilter.vhd
read_vhdl -vhdl2008 $root_dir/src/rtl/HIL_AXI_Top.vhd
check_syntax
puts "SYNTAX_CHECK_OK"
```

Rodar (leva ~15-20s):

```bash
/opt/Xilinx/Vivado/2024.1/bin/vivado -mode batch -nolog -nojournal -notrace \
  -source syn/hil/check_hil_axi_top_syntax.tcl 2>&1 | tail -10
```

Esperado: `INFO: [Vivado 12-4796] No errors or warning reported.` seguido de
`SYNTAX_CHECK_OK` (confirmado rodando este comando antes de qualquer mudança
nesta task — já verificado durante o planejamento).

- [ ] **Step 2: Declarar o sinal novo**

Em `src/rtl/HIL_AXI_Top.vhd`, linha 190 (logo após `signal carrier_tick_s : std_logic;`):

```vhdl
    signal carrier_tick_s : std_logic;
    signal vf_irq_tick_s  : std_logic;  -- pico+vale (LOAD_BOTH_EDGES); alimenta a IRQ real
```

- [ ] **Step 3: Habilitar `LOAD_BOTH_EDGES` e conectar `sample_tick_o`**

Linha 464 (generic map do `NPCManager_Inst`):

```vhdl
        LOAD_BOTH_EDGES => true,   -- era false; agora IRQ real dispara em pico+vale
```

Linha 479 (port map do `NPCManager_Inst`):

```vhdl
        sample_tick_o   => vf_irq_tick_s,   -- era "open"
```

- [ ] **Step 4: Repor a porta de topo (a que alimenta `IRQ_F2P`) para o sinal novo**

Linha 429:

```vhdl
    carrier_tick_o <= vf_irq_tick_s;  -- era carrier_tick_s; contador de diagnostico continua em carrier_tick_s (inalterado)
```

Confirmar que o contador de diagnóstico (linha ~1054, `if carrier_tick_s = '1' then`) **não foi tocado** — ele deve continuar lendo `carrier_tick_s`, não `vf_irq_tick_s`.

- [ ] **Step 5: Rodar o syntax-check de novo e confirmar que passa**

```bash
/opt/Xilinx/Vivado/2024.1/bin/vivado -mode batch -nolog -nojournal -notrace \
  -source syn/hil/check_hil_axi_top_syntax.tcl 2>&1 | tail -10
```

Esperado: mesmo `SYNTAX_CHECK_OK` de antes — a mudança é só re-roteamento de
sinais internos, não deve introduzir erro de sintaxe/elaboração.

- [ ] **Step 6: Commit**

```bash
git add src/rtl/HIL_AXI_Top.vhd syn/hil/check_hil_axi_top_syntax.tcl
git commit -m "feat(rtl): HIL_AXI_Top.vhd religa IRQ_F2P para pico+vale da portadora"
```

---

## Task 3: cocotb — novo método canônico de teste L3 (travado na IRQ)

**Files:**
- Modify: `verification/cocotb/tests/test_top_hil.py`, dentro de `test_top_hil_pwm_replay_l3` (os números de linha originais 436-513 deslocam depois da Task 1 inserir um teste novo mais acima no mesmo arquivo — localizar pelo conteúdo mostrado abaixo, não pela linha absoluta)

**Interfaces:**
- Consumes: `dut.sample_tick_o` pulsando 2×/período (Task 1).
- Produces: `metrics.json` no mesmo formato de sempre (`nrmse_i_alpha`, `nrmse_i_beta`, `mae_flux_alpha_wb`, `mae_flux_beta_wb`, `mae_speed_rad_s`) — só muda **quando** a referência é escrita, não o formato do resultado.

Este teste já existe e já roda; a mudança é substituir a atualização de
referência "contínua a cada passo do solver" pela atualização "só na borda de
`sample_tick_o`", que é o que o PS real fará depois da Task 5.

- [ ] **Step 1: Rodar o teste hoje e guardar o resultado atual como baseline**

```bash
cd verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 HIL_VF_DURATION_S=0.1 \
HIL_L3_REF_MODE=vf HIL_L3_VF_BASE_HZ=60 HIL_L3_VF_ACC_HZ_S=60 \
HIL_L3_STEPS=769231 HIL_L3_WARMUP_STEPS=400 HIL_L3_RECORD_INTERVAL=80 \
HIL_L3_OUT_DIR=/tmp/l3_irq_baseline \
uv run python run.py --sim nvc --top top_hil --test top_hil -k test_top_hil_pwm_replay_l3
cat /tmp/l3_irq_baseline/metrics.json
```

Anotar `nrmse_i_alpha`/`nrmse_i_beta` — servem só de referência de que o teste
continua rodando depois da mudança (não é uma comparação formal contra o
método antigo, que não nos interessa mais).

- [ ] **Step 2: Substituir a atualização de referência por uma travada em `sample_tick_o`**

Em `verification/cocotb/tests/test_top_hil.py`, a função `drive_refs` fica
igual — só muda **quem a chama e quando**. Localizar (pelo conteúdo, não pela
linha — desloca depois da Task 1) o trecho logo após a definição de
`drive_refs`, que hoje é:

```python
    drive_refs(0.0)
    dut.pwm_enb_i.value = 1
    dut.pwm_clear_i.value = 0
```

e substituir por:

```python
    tick_hz = 2 * pwm_hz  # LOAD_BOTH_EDGES: pico+vale
    latest_cmd_state: dict[str, float] = drive_refs(0.0)  # "queimada de partida", espelha main.c:117

    async def vf_irq_driver():
        """Mimetiza o PS real (src/ps_app/vf_irq.c, Task 5): so escreve uma
        nova referencia quando a IRQ real (sample_tick_o, pico+vale) dispara,
        nao em intervalo fixo de software."""
        nonlocal latest_cmd_state
        tick_count = 0
        while True:
            await RisingEdge(dut.sample_tick_o)
            tick_count += 1
            latest_cmd_state = drive_refs(tick_count / tick_hz)

    cocotb.start_soon(vf_irq_driver())
    dut.pwm_enb_i.value = 1
    dut.pwm_clear_i.value = 0
```

E substituir, dentro do loop principal (localizar pelo conteúdo — o `for`
que itera `sample_steps` e chama `drive_refs` a cada passo do solver):

```python
    for step in range(sample_steps):
        cmd_state = drive_refs(step * params.ts)
```

por:

```python
    for step in range(sample_steps):
        cmd_state = latest_cmd_state
```

- [ ] **Step 3: Rodar de novo e confirmar que passa (mesmo formato de métricas)**

```bash
cd verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 HIL_VF_DURATION_S=0.1 \
HIL_L3_REF_MODE=vf HIL_L3_VF_BASE_HZ=60 HIL_L3_VF_ACC_HZ_S=60 \
HIL_L3_STEPS=769231 HIL_L3_WARMUP_STEPS=400 HIL_L3_RECORD_INTERVAL=80 \
HIL_L3_OUT_DIR=/tmp/l3_irq_locked \
uv run python run.py --sim nvc --top top_hil --test top_hil -k test_top_hil_pwm_replay_l3
cat /tmp/l3_irq_locked/metrics.json
```

Esperado: teste passa (mesmas chaves em `metrics.json`: `nrmse_i_alpha`,
`nrmse_i_beta`, `mae_flux_alpha_wb`, `mae_flux_beta_wb`, `mae_speed_rad_s`);
os valores podem diferir do baseline do Step 1 — isso é esperado, não é uma
regressão (o método de referência mudou de propósito).

- [ ] **Step 4: Commit**

```bash
git add verification/cocotb/tests/test_top_hil.py
git commit -m "feat(cocotb): L3 passa a travar a referencia V/f na IRQ real (pico+vale), nao em relogio livre"
```

---

## Task 4: PS software — dobrar `VF_TICK_HZ` para 2 kHz

**Files:**
- Modify: `src/ps_app/vf_ctrl.h:15`
- Test: `src/ps_app/test_vf_tick_rate.c` (novo, standalone, sem hardware)

**Interfaces:**
- Consumes: nenhuma dependência de VHDL/cocotb.
- Produces: `TS = 1/VF_TICK_HZ` correto para Task 5 (que passa a chamar `vf_tick()` a cada borda da IRQ, 2x/período da portadora).

`vf_tick()` (`vf_ctrl.c`) não é testável isoladamente sem hardware real (chama
`gpio_set_vref`/`gpio_set_pwm_ctrl`, que fazem `mmap` de `/dev/mem`). Este
teste isola só a matemática do incremento angular (`theta += omega*TS`), que
é o que quebra se `VF_TICK_HZ` não acompanhar a nova taxa de chamada.

- [ ] **Step 1: Escrever o teste que falha**

Criar `src/ps_app/test_vf_tick_rate.c`:

```c
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
    int expected_ticks = (int)((float)VF_TICK_HZ / freq_hz + 0.5f);
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd src/ps_app
gcc -O2 -Wall -Wextra -o /tmp/test_vf_tick_rate test_vf_tick_rate.c -lm
/tmp/test_vf_tick_rate
```

Esperado: `FALHOU: VF_TICK_HZ deveria ser 2000 (pico+vale a 1kHz), e' 1000`,
exit code 1 (`VF_TICK_HZ` ainda é `1000u` neste ponto).

- [ ] **Step 3: Aplicar a mudança**

Em `src/ps_app/vf_ctrl.h`, linha 15, e atualizar o comentário acima (linhas
6-14) que hoje justifica `1000u` com o raciocínio de oversampling antigo:

```c
/*
 * Taxa de atualização da referência V/F [Hz]. Igual a 2x a portadora PWM
 * (1 kHz, definida por PWM_FREQ no HIL_AXI_Top sintetizado), porque a
 * referência agora é escrita a cada interrupção real da portadora — pico E
 * vale (LOAD_BOTH_EDGES, ver docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md),
 * disparada por src/ps_app/vf_irq.c. Antes deste trabalho, o tick rodava
 * livre por software (clock_nanosleep) a 1 kHz, sem travamento de fase com
 * a portadora — daí o histórico de jitter documentado na dissertação.
 * vf_ctrl.c deriva o passo de integração TS = 1/VF_TICK_HZ.
 */
#define VF_TICK_HZ  2000u
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd src/ps_app
gcc -O2 -Wall -Wextra -o /tmp/test_vf_tick_rate test_vf_tick_rate.c -lm
/tmp/test_vf_tick_rate
```

Esperado: `VF_TICK_HZ=2000 ticks_por_volta=34 esperado=34` (aproximando
2000/60), seguido de `OK`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/ps_app/vf_ctrl.h src/ps_app/test_vf_tick_rate.c
git commit -m "fix(ps_app): VF_TICK_HZ 1000->2000, acompanha a IRQ real de pico+vale"
```

---

## Task 5: PS software — `vf_irq.c`/`vf_irq.h` (UIO) substitui a thread livre

**Files:**
- Create: `src/ps_app/vf_irq.c`
- Create: `src/ps_app/vf_irq.h`
- Modify: `src/ps_app/main.c:80-99` (substitui `vf_clock_thread`), `src/ps_app/Makefile:19` (`SRCS`)

**Interfaces:**
- Consumes: `vf_tick()` (já existe, `vf_ctrl.h`); nó de device-tree com `label = "vf_irq"` (Task 6 — mas o código compila e é revisável sem ele; só falha em runtime real por falta do `/dev/uioX`, que é esperado e fora de escopo aqui).
- Produces: `int vf_irq_start(void)`, `void vf_irq_stop(void)` — mesma assinatura de uso que `setup_vf_timer()`/`cancel_timer()` tinham, para minimizar mudança em `main.c`.

- [ ] **Step 1: Criar o header**

`src/ps_app/vf_irq.h`:

```c
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
```

- [ ] **Step 2: Criar a implementação**

`src/ps_app/vf_irq.c`:

```c
#include "vf_irq.h"
#include "vf_ctrl.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <pthread.h>

#define UIO_LABEL       "vf_irq"
#define UIO_CLASS_DIR   "/sys/class/uio"
#define UIO_DEV_FMT     "/dev/%s"

static int           uio_fd = -1;
static pthread_t     uio_tid;
static volatile int  uio_active = 0;

/* Procura em /sys/class/uio/uioN/name o dispositivo cujo conteudo bate com
 * UIO_LABEL, e devolve o nome do node em /dev (ex: "uio0"). Nao assume
 * indice fixo — o numero de uioN pode mudar entre boots conforme a ordem
 * de probe dos drivers. */
static int find_uio_device(char *out_name, size_t out_len)
{
    DIR *d = opendir(UIO_CLASS_DIR);
    if (!d) {
        fprintf(stderr, "vf_irq: opendir %s: %s\n", UIO_CLASS_DIR, strerror(errno));
        return -1;
    }
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strncmp(ent->d_name, "uio", 3) != 0) continue;
        char name_path[256];
        snprintf(name_path, sizeof(name_path), "%s/%s/name", UIO_CLASS_DIR, ent->d_name);
        FILE *f = fopen(name_path, "r");
        if (!f) continue;
        char label[128] = {0};
        if (fgets(label, sizeof(label), f) != NULL) {
            label[strcspn(label, "\n")] = '\0';
        }
        fclose(f);
        if (strcmp(label, UIO_LABEL) == 0) {
            snprintf(out_name, out_len, "%s", ent->d_name);
            closedir(d);
            return 0;
        }
    }
    closedir(d);
    fprintf(stderr, "vf_irq: nenhum /sys/class/uio/uioN com label \"%s\"\n", UIO_LABEL);
    return -1;
}

static void *uio_irq_thread(void *arg)
{
    (void)arg;
    while (uio_active) {
        uint32_t count;
        ssize_t n = read(uio_fd, &count, sizeof(count));
        if (n != (ssize_t)sizeof(count)) {
            if (!uio_active) break;  /* fd fechado por vf_irq_stop() */
            fprintf(stderr, "vf_irq: read /dev/uio inesperado (n=%zd): %s\n",
                    n, strerror(errno));
            break;
        }
        if (!uio_active) break;
        vf_tick();
        /* Contrato UIO: escrever de volta reabilita a IRQ no kernel */
        uint32_t reenable = 1;
        if (write(uio_fd, &reenable, sizeof(reenable)) != (ssize_t)sizeof(reenable)) {
            fprintf(stderr, "vf_irq: write reenable falhou: %s\n", strerror(errno));
            break;
        }
    }
    return NULL;
}

int vf_irq_start(void)
{
    char dev_name[64];
    if (find_uio_device(dev_name, sizeof(dev_name)) != 0) return -1;

    char dev_path[128];
    snprintf(dev_path, sizeof(dev_path), UIO_DEV_FMT, dev_name);
    uio_fd = open(dev_path, O_RDWR);
    if (uio_fd < 0) {
        fprintf(stderr, "vf_irq: open %s: %s\n", dev_path, strerror(errno));
        return -1;
    }

    vf_tick();  /* "queimada de partida", mesma logica que setup_vf_timer() tinha */
    uio_active = 1;
    if (pthread_create(&uio_tid, NULL, uio_irq_thread, NULL) != 0) {
        perror("vf_irq: pthread_create");
        uio_active = 0;
        close(uio_fd);
        uio_fd = -1;
        return -1;
    }
    return 0;
}

void vf_irq_stop(void)
{
    if (!uio_active) return;
    uio_active = 0;
    if (uio_fd >= 0) close(uio_fd);  /* desbloqueia o read() pendente */
    pthread_join(uio_tid, NULL);
    uio_fd = -1;
}
```

- [ ] **Step 3: Trocar `main.c` para usar o módulo novo**

Adicionar o include novo junto dos outros headers do projeto, no topo do
arquivo (`src/ps_app/main.c:1-5`):

```c
#include "gpio.h"
#include "vf_ctrl.h"
#include "vf_irq.h"
#include "telemetry.h"
#include "dma_telem.h"
#include "pwm_events.h"
```

Localizar pelo conteúdo (não pela linha) o bloco inteiro de
`vf_clock_tid`/`vf_clock_active`/`vf_clock_thread` até o fim de
`cancel_timer()`, hoje:

```c
/* ── V/F reference clock on a dedicated thread ──────────────────────────── */
static pthread_t vf_clock_tid;
static volatile int vf_clock_active = 0;

static void *vf_clock_thread(void *arg)
{
    (void)arg;
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (running && vf_clock_active) {
        next.tv_nsec += 1000000000L / VF_TICK_HZ;
        if (next.tv_nsec >= 1000000000L) {
            next.tv_sec++;
            next.tv_nsec -= 1000000000L;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        if (vf_clock_active) vf_tick();
    }
    return NULL;
}

static void set_udp_reuse(int sock)
{
    /* ... corpo inalterado, nao mexer ... */
}

static int setup_vf_timer(void)
{
    /* Release any clear/reset state left by boot or test_fpga. */
    vf_tick();
    vf_clock_active = 1;
    if (pthread_create(&vf_clock_tid, NULL, vf_clock_thread, NULL) != 0) {
        vf_clock_active = 0;
        perror("pthread_create vf_clock");
        return -1;
    }
    return 0;
}

static void cancel_timer(void)
{
    if (!vf_clock_active) return;
    vf_clock_active = 0;
    pthread_join(vf_clock_tid, NULL);
}
```

`set_udp_reuse` fica exatamente onde está, sem mudança — só está listada aqui
para mostrar que ela fica *entre* o bloco removido e `cancel_timer()` no
arquivo real; não mover nem duplicar. As partes que mudam são
`vf_clock_tid`/`vf_clock_active`/`vf_clock_thread`/`setup_vf_timer`/
`cancel_timer`, substituídas por:

```c
/* ── V/F reference clock: consome a IRQ real da portadora via UIO ────────
 * Ver src/ps_app/vf_irq.c e docs/superpowers/specs/2026-07-04-vf-pwm-irq-sync-design.md.
 * Substitui a antiga thread de clock_nanosleep livre. */
static int setup_vf_timer(void)
{
    /* vf_irq_start() ja' faz a "queimada de partida" (vf_tick() antes de
     * armar) e sobe a thread que consome /dev/uioX. */
    return vf_irq_start();
}

static void cancel_timer(void)
{
    vf_irq_stop();
}
```

(`set_udp_reuse`, entre os dois blocos, continua exatamente igual.)

- [ ] **Step 4: Adicionar `vf_irq.c` ao build**

Em `src/ps_app/Makefile`, linha 19:

```makefile
SRCS        := main.c gpio.c vf_ctrl.c vf_irq.c telemetry.c dma_telem.c pwm_events.c
```

- [ ] **Step 5: Compilar (nativo, sem hardware) e confirmar que não quebra o build**

```bash
cd src/ps_app
make native
```

Esperado: build termina com `Built native: hil_controller_native` sem erros
de compilação/link (o binário resultante, se executado, falhará em
`vf_irq_start()` por não achar `/dev/class/uio` real neste ambiente — isso é
esperado e não é o que este step valida; o step valida só compilação).

- [ ] **Step 6: Commit**

```bash
git add src/ps_app/vf_irq.c src/ps_app/vf_irq.h src/ps_app/main.c src/ps_app/Makefile
git commit -m "feat(ps_app): consome a IRQ real da portadora via UIO (vf_irq.c), substitui thread livre"
```

---

## Task 6: Device-tree — nó UIO para `IRQ_F2P[0]`

**Files:**
- Modify: `syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`

**Interfaces:**
- Consumes: nada de outra task.
- Produces: nó `/dev/uioX` com `label="vf_irq"` — o nome que `vf_irq.c` (Task 5) procura. Só produz efeito depois de um rebuild do PetaLinux (fora de escopo).

- [ ] **Step 1: Adicionar o nó**

Em `syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`,
adicionar dentro do bloco `/ { ... }` já existente (junto de `reserved-memory`):

```dts
/include/ "system-conf.dtsi"
/ {
    reserved-memory {
        #address-cells = <1>;
        #size-cells = <1>;
        ranges;

        hil_dma_buf: buffer@0f000000 {
            reg = <0x0f000000 0x01000000>;
            no-map;
        };
    };

    /* IRQ_F2P[0] = carrier_tick_o (pico+vale, LOAD_BOTH_EDGES) — consumida
     * por src/ps_app/vf_irq.c via /dev/uioX. Numero de IRQ (29 = SPI 61-32,
     * convencao Zynq-7000 para F2P[0]) precisa ser confirmado contra o
     * bloco de IP real na primeira sintese apos este trabalho — nao usar
     * as cegas se o endereco/numero divergir do relatorio do Vivado. */
    vf_irq: vf_irq@0 {
        compatible = "generic-uio";
        interrupt-parent = <&intc>;
        interrupts = <0 29 4>;
        interrupt-names = "vf_irq";
        label = "vf_irq";
    };
};
```

- [ ] **Step 2: Validar a sintaxe do device-tree**

```bash
/opt/Xilinx/Vivado/2024.1/bin/dtc -I dts -O dtb -o /tmp/vf_irq_check.dtb \
  syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi
```

Esperado: pode reportar warnings sobre `intc`/labels externos não resolvidos
(esperado — `system-conf.dtsi` incluído não está neste diretório isolado),
mas **sem erro de sintaxe** no nó `vf_irq` em si (chaves balanceadas,
propriedades bem formadas). Se o `dtc` não conseguir resolver `/include/
"system-conf.dtsi"` (arquivo gerado pelo PetaLinux, não existe fora de um
build), rodar só a checagem de chaves balanceadas:

```bash
python3 -c "
content = open('syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi').read()
assert content.count('{') == content.count('}'), 'chaves desbalanceadas'
print('OK: chaves balanceadas')
"
```

- [ ] **Step 3: Commit**

```bash
git add syn/hil/ebaz4205_petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi
git commit -m "feat(petalinux): no de device-tree UIO (label vf_irq) para IRQ_F2P[0]"
```

---

## Fora de escopo (próxima etapa, não neste plano)

- Confirmar o número real da IRQ (29) contra o relatório do Vivado após a
  primeira ressíntese.
- Rebuild do PetaLinux (bitbake) para o nó de device-tree ter efeito.
- Ressíntese do bitstream com as mudanças da Task 2.
- Reflash da EBAZ4205 e validação end-to-end em hardware real (L4) —
  primeira vez que L4 rodaria neste projeto.
- Reexecução de todos os resultados L3 já existentes (obsoletos pelo novo
  método da Task 3), empilhada sobre a rerodada de Rs/J já pendente
  (`verification/cocotb/campaigns/run_campanha_02_motor_fix.sh`).
