# Diagramas do HIL — refatoração em 6 figuras (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refazer o conjunto de diagramas D2 do HIL em 6 figuras por subsistema (mapa + FPGA-Top + Solver + PS + Backend + Frontend), aplicando a regra de fronteira para que a leitura completa explique o sistema sem repetição.

**Architecture:** Diagram-as-code com D2 (motor ELK, ortogonal, paisagem, monocromático). Cada `.d2` é uma figura; `build.sh` varre `*.d2` e exporta SVG+PNG para `img/`. Cada figura detalha só o seu interior e mostra vizinhos como caixa-preta de borda dupla.

**Tech Stack:** D2 v0.7.1 (`~/.local/bin/d2`), motor de layout ELK, chromium do playwright (raster PNG, já instalado).

## Global Constraints

- Diretório de trabalho: `docs/diagrams/`. Renderizar sempre com `./build.sh` (já usa `-l elk -t 0`).
- Estilo monocromático fixo. **Cabeçalho de classes compartilhado** (copiar verbatim no topo de cada `.d2`):

```d2
vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}
```

- **Convenções (verbatim do spec):** `grp` tracejado = subsistema; `dom` tracejado fino = domínio de clock; `fast` cinza = domínio 200 MHz; `cdc` borda tracejada = travessia de clock; **`ext` borda dupla = vizinho caixa-preta (detalhado na sua própria figura)**; seta sólida = dados; seta tracejada (`style.stroke-dash: 4`) = controle/IRQ/comandos; rótulo de seta = taxa.
- **Donos dos conceitos transversais:** cadeia de taxas fim-a-fim → **00**; clocks 100/200 MHz + CDC + decimador → **01**; Q14.28 + passo 130 ns → **02**; regimes temporais ISR/DMA → **03**; pirâmide/decimação de display → **04**.
- Texto dos rótulos em ASCII (sem acentos) como nos `.d2` atuais.
- Os arquivos em `docs/diagrams/` são **untracked** no git (diretório novo): renomear com `mv` simples (não `git mv`).
- Commits incrementais por figura. Branch atual: `feat/dma-telemetria` (não é a default — pode commitar).

---

### Task 1: Figura 00 — Mapa (contexto)

Reescreve `00-system.d2` para ser puramente o mapa: três subsistemas como caixa-preta (`ext`), a malha de controle, o caminho de telemetria e a **cadeia de taxas global**. Nenhum interior.

**Files:**
- Modify: `docs/diagrams/00-system.d2` (substituir conteúdo inteiro)
- Render: `docs/diagrams/img/00-system.{svg,png}`

**Interfaces:**
- Consumes: cabeçalho de classes compartilhado (Global Constraints).
- Produces: nada (figura terminal).

- [ ] **Step 1: Substituir o conteúdo de `00-system.d2`**

```d2
# =============================================================================
# Figura 00 - Mapa (contexto). Dono da cadeia de taxas fim-a-fim.
# Subsistemas como caixa-preta (ext). Nenhum interior aqui.
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

sut: "Sistema em Teste\nPS - ARM Cortex-A9 - Linux/C (soft-RT)\n[fig. 03]" {class: ext}
hil: "Hardware in the Loop\nFPGA / PL - VHDL (hard-RT)\nclocks: 100 MHz (AXI) + 200 MHz (solver)\n[fig. 01 / 02]" {class: ext}
ws:  "Workstation\nPC Host - Go + TypeScript\n[fig. 04 / 05]" {class: ext}

sut -> hil: "refs V/F (AXI-Lite) @ 1 kHz" {class: arrow}
hil -> sut: "carrier_tick (IRQ) @ 1 kHz" {class: arrow; style.stroke-dash: 4}
hil -> ws: "telemetria (UDP) ~100 kHz" {class: arrow}
ws -> sut: "comandos (UDP)" {class: arrow; style.stroke-dash: 4}

cadeia: "Cadeia de taxas: solver ~7,69 MHz (passo 130 ns) -> anti-aliasing (fc~40 kHz) -> decimador /77 -> ~100 kHz (UDP) -> decimacao de display (min/max, no host)" {
  near: bottom-center
  shape: text
  style: {font-color: black; font-size: 20}
}
```

- [ ] **Step 2: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 00-system.d2 img/00-system.png`
Expected: `success: successfully compiled 00-system.d2 ...`

- [ ] **Step 3: Verificar visualmente (ler o PNG)**

Checklist: (a) só 3 caixas `ext` de borda dupla, nenhum interior; (b) malha de controle (refs + carrier_tick) e telemetria visíveis; (c) a cadeia de taxas aparece na legenda; (d) nenhum bloco interno de subsistema.

- [ ] **Step 4: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add docs/diagrams/00-system.d2 docs/diagrams/img/00-system.png docs/diagrams/img/00-system.svg
git commit -m "docs(diagramas): figura 00 vira mapa de contexto puro"
```

---

### Task 2: Figura 01 — FPGA / HIL_AXI_Top

Renomeia `01-solver.d2` → `01-fpga-top.d2` e reescreve com foco na integração da PL: dois domínios de clock + CDC + decimador + DMA. O **TIM_Solver vira caixa-preta** (`ext`) dentro da banda do domínio 200 MHz.

**Files:**
- Rename+Modify: `docs/diagrams/01-solver.d2` → `docs/diagrams/01-fpga-top.d2`
- Delete (órfãos): `docs/diagrams/img/01-solver.{svg,png}`
- Render: `docs/diagrams/img/01-fpga-top.{svg,png}`

**Interfaces:**
- Consumes: cabeçalho de classes compartilhado.
- Produces: a caixa-preta `TIM_Solver` cuja contraparte detalhada é a fig. 02.

- [ ] **Step 1: Renomear o arquivo e remover imagens órfãs**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/diagrams
mv 01-solver.d2 01-fpga-top.d2
rm -f img/01-solver.svg img/01-solver.png
```

- [ ] **Step 2: Substituir o conteúdo de `01-fpga-top.d2`**

```d2
# =============================================================================
# Figura 01 - FPGA / HIL_AXI_Top (integracao na PL).
# Dono de: dominios de clock 100/200 MHz + CDC + decimador + DMA.
# TIM_Solver = caixa-preta (detalhado na fig. 02).
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

ps_in:  "PS (Linux/C)\nAXI-Lite @ 1 kHz" {class: ext}

hil: HIL_AXI_Top (PL - VHDL) {
  class: grp

  d100: "Dominio AXI / PWM - 100 MHz (FCLK0)" {
    class: dom
    regs: "Banco de\nRegistradores" {class: box}
    npc: "Modulador NPC\n3 niveis - carrier 1 kHz" {class: box}
    v: "Estados -> Tensao\n+-Vdc/2" {class: box}
    irq: "Gera carrier_tick\n-> IRQ_F2P" {class: box}
    regs -> npc: {class: arrow}
    npc -> v: "gate states" {class: arrow}
    npc -> irq: {class: arrow}
  }

  cdc_in: "CDC\n100 -> 200 MHz" {class: cdc}

  d200: "Dominio Solver - 200 MHz (MMCM)" {
    class: dom
    style.fill: "#d9d9d9"
    solver: "TIM_Solver\n(nucleo numerico - ver fig. 02)" {class: ext}
  }

  cdc_out: "CDC + snapshot\n200 -> 100 MHz" {class: cdc}

  filt: "Anti-aliasing\nButterworth 2a ord. (fc~40 kHz)" {class: box}
  decim: "Decimador\n/77" {class: box}
  dma: "AXI-Stream 256-bit\n-> AXI DMA (S2MM)" {class: box}

  d100.v -> cdc_in: "V_a V_b V_c" {class: arrow}
  cdc_in -> d200.solver: {class: arrow}
  d200.solver -> cdc_out: "I_ab psi_ab w\n~7,69 MHz (nativo)" {class: arrow}
  cdc_out -> filt: {class: arrow}
  filt -> decim: {class: arrow}
  decim -> dma: "~100 kHz" {class: arrow}
}

ps_out: "PS (Linux/C)\nDMA -> UDP ~100 kHz" {class: ext}

ps_in -> hil.d100.regs: "refs V/F + coeficientes A,B" {class: arrow}
hil.d100.irq -> ps_in: "IRQ @ 1 kHz" {class: arrow; style.stroke-dash: 4}
hil.dma -> ps_out: "burst 128 frames (~1,28 ms)" {class: arrow}

legenda: "Cinza = dominio 200 MHz   |   borda dupla = caixa-preta (outra figura)   |   tracejado fino = CDC   |   taxas em cada estagio" {
  near: bottom-center
  shape: text
  style: {font-color: black; font-size: 18}
}
```

- [ ] **Step 3: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 01-fpga-top.d2 img/01-fpga-top.png`
Expected: `success: successfully compiled 01-fpga-top.d2 ...`

- [ ] **Step 4: Verificar visualmente**

Checklist: (a) duas bandas `dom` (100 e 200 MHz); (b) `TIM_Solver` é caixa de borda dupla, sem internos; (c) dois `cdc`; (d) decimador `/77` e DMA presentes; (e) PS é `ext`.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add -A docs/diagrams/01-fpga-top.d2 docs/diagrams/img/01-fpga-top.png docs/diagrams/img/01-fpga-top.svg
git commit -m "docs(diagramas): figura 01 foca em HIL_AXI_Top; solver vira caixa-preta"
```

---

### Task 3: Figura 02 — TIM_Solver (núcleo numérico)

Cria `02-solver.d2`: o interior do solver. Dono de Q14.28 e do passo de 130 ns. Tudo no domínio rápido (`fast`).

**Files:**
- Create: `docs/diagrams/02-solver.d2`
- Render: `docs/diagrams/img/02-solver.{svg,png}`

**Interfaces:**
- Consumes: entrada `V_a V_b V_c` e saída `I/psi/w` como bordas `ext` (contraparte da fig. 01).
- Produces: nada.

- [ ] **Step 1: Criar `02-solver.d2`**

```d2
# =============================================================================
# Figura 02 - TIM_Solver (nucleo numerico). Dono de Q14.28 e passo 130 ns.
# Estrutura real (src/rtl/TIM_Solver.vhd): timer, Clarke, matrizes A/B (shadow)
# + Y estrutural (acoplamento nao-linear X.X), solver bilinear DSP48, estado X,
# mapeamento de saidas.
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

vin: "V_a V_b V_c\n(do HIL_AXI_Top, fig. 01)" {class: ext}

solver: "TIM_Solver - dominio 200 MHz (MMCM) - Q14.28, 42-bit" {
  class: grp
  style.fill: "#d9d9d9"

  timer: "Timer de passo\n26 ciclos = 130 ns" {class: fast}
  clarke: "Transformada de Clarke\nV_abc -> V_alpha V_beta" {class: fast}
  coef: "Coeficientes A, B (shadow)\naplicados quando idle" {class: fast}
  ymat: "Matriz Y (estrutural)\nacoplamento nao-linear X.X" {class: fast}
  bilinear: "Solver Bilinear (DSP48E1)\ndX = A X[k] + B U + Y(X.X)" {class: fast}
  xstate: "Vetor de Estado X[k]\n(registradores)" {class: fast}
  outmap: "Mapeamento de Saidas\nI_alpha I_beta  psi_alpha psi_beta  w_m" {class: fast}

  clarke -> bilinear: "U = V_alpha V_beta" {class: arrow}
  coef -> bilinear: "A, B" {class: arrow; style.stroke-dash: 4}
  ymat -> bilinear: {class: arrow}
  xstate -> bilinear: "X[k]" {class: arrow}
  timer -> bilinear: "start (a cada 130 ns)" {class: arrow; style.stroke-dash: 4}
  bilinear -> xstate: "X[k+1]" {class: arrow}
  xstate -> outmap: {class: arrow}
}

out: "I_ab  psi_ab  w\n(para anti-aliasing/decimador, fig. 01)" {class: ext}

vin -> solver.clarke: {class: arrow}
solver.outmap -> out: {class: arrow}

legenda: "Tudo no dominio 200 MHz (cinza). Bilinear = termo linear A X + B U mais termo nao-linear via matriz Y (acoplamento velocidade-fluxo). Ponto fixo Q14.28." {
  near: bottom-center
  shape: text
  style: {font-color: black; font-size: 18}
}
```

- [ ] **Step 2: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 02-solver.d2 img/02-solver.png`
Expected: `success: successfully compiled 02-solver.d2 ...`

- [ ] **Step 3: Verificar visualmente**

Checklist: (a) blocos internos: timer, Clarke, A/B shadow, Y, bilinear, X, mapeamento; (b) laço X[k] -> bilinear -> X[k+1]; (c) Q14.28 e 130 ns presentes; (d) só entrada/saída como `ext`.

- [ ] **Step 4: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add docs/diagrams/02-solver.d2 docs/diagrams/img/02-solver.png docs/diagrams/img/02-solver.svg
git commit -m "docs(diagramas): figura 02 detalha o nucleo numerico do TIM_Solver"
```

---

### Task 4: Figura 03 — PS / daemon

Renomeia `02-ps-daemon.d2` → `03-ps-daemon.d2`. Mantém os dois regimes temporais; reclassifica PL e Workstation como `ext` (borda dupla).

**Files:**
- Rename+Modify: `docs/diagrams/02-ps-daemon.d2` → `docs/diagrams/03-ps-daemon.d2`
- Delete (órfãos): `docs/diagrams/img/02-ps-daemon.{svg,png}`
- Render: `docs/diagrams/img/03-ps-daemon.{svg,png}`

**Interfaces:**
- Consumes: cabeçalho compartilhado.
- Produces: nada.

- [ ] **Step 1: Renomear e remover órfãos**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/diagrams
mv 02-ps-daemon.d2 03-ps-daemon.d2
rm -f img/02-ps-daemon.svg img/02-ps-daemon.png
```

- [ ] **Step 2: Substituir o conteúdo de `03-ps-daemon.d2`**

```d2
# =============================================================================
# Figura 03 - PS / daemon (src/ps_app). Dono dos dois regimes temporais:
# controle por ISR @ 1 kHz e telemetria por DMA @ ~100 kHz. Vizinhos = ext.
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

pl: "PL (FPGA / VHDL)\nHIL_AXI_Top [fig. 01]" {class: ext}

daemon: "hil-daemon (PS - ARM Cortex-A9 - Linux/C, soft-RT)" {
  class: grp

  ctrl: "Malha de Controle - ISR por carrier_tick @ 1 kHz" {
    class: dom
    main: "Maquina de Estados\nidle / run / pause / stop" {class: box}
    vf: "Controle V/F\n(rampa de freq/tensao)" {class: box}
    gpio: "Escrita AXI-Lite (mmap)\nv_a v_b v_c + coeficientes" {class: box}
    main -> vf: {class: arrow}
    vf -> gpio: {class: arrow}
  }

  telem: "Telemetria - DMA @ ~100 kHz" {
    class: dom
    dma: "Driver DMA (S2MM)\nburst 128 frames (~1,28 ms)" {class: box}
    pack: "Empacota -> UDP" {class: box}
    pwm: "Eventos NPC -> UDP" {class: box}
    dma -> pack: {class: arrow}
  }
}

host: "Workstation (Gateway Go) [fig. 04]" {class: ext}

pl -> daemon.ctrl.main: "carrier_tick (IRQ @ 1 kHz)" {class: arrow; style.stroke-dash: 4}
daemon.ctrl.gpio -> pl: "refs + coeficientes (AXI-Lite)" {class: arrow}
pl -> daemon.telem.dma: "AXI-Stream / DMA (~100 kHz)" {class: arrow}
pl -> daemon.telem.pwm: "estados de gate" {class: arrow}
host -> daemon.ctrl.main: "comandos (UDP)" {class: arrow; style.stroke-dash: 4}
daemon.telem.pack -> host: "telemetria (UDP ~100 kHz)" {class: arrow}
daemon.telem.pwm -> host: "eventos PWM (UDP)" {class: arrow}

legenda: "tracejado = controle/IRQ   |   solido = dados   |   borda dupla = caixa-preta   |   o tempo real estrito (130 ns) vive na PL, nao no PS" {
  near: bottom-center
  shape: text
  style: {font-color: black; font-size: 18}
}
```

- [ ] **Step 3: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 03-ps-daemon.d2 img/03-ps-daemon.png`
Expected: `success: successfully compiled 03-ps-daemon.d2 ...`

- [ ] **Step 4: Verificar visualmente**

Checklist: (a) duas bandas (ISR 1 kHz / DMA 100 kHz); (b) PL e Workstation são `ext`; (c) legenda crava "hard-RT vive na PL".

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add -A docs/diagrams/03-ps-daemon.d2 docs/diagrams/img/03-ps-daemon.png docs/diagrams/img/03-ps-daemon.svg
git commit -m "docs(diagramas): renumera PS para figura 03; vizinhos como caixa-preta"
```

---

### Task 5: Figura 04 — Backend / gateway Go

Renomeia `03-backend.d2` → `04-backend.d2`. Dono da pirâmide/decimação de display. Placa e frontend como `ext`.

**Files:**
- Rename+Modify: `docs/diagrams/03-backend.d2` → `docs/diagrams/04-backend.d2`
- Delete (órfãos): `docs/diagrams/img/03-backend.{svg,png}`
- Render: `docs/diagrams/img/04-backend.{svg,png}`

- [ ] **Step 1: Renomear e remover órfãos**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/diagrams
mv 03-backend.d2 04-backend.d2
rm -f img/03-backend.svg img/03-backend.png
```

- [ ] **Step 2: Substituir o conteúdo de `04-backend.d2`**

```d2
# =============================================================================
# Figura 04 - Backend / gateway Go (apps/hil-go). Dono da piramide / decimacao
# de display. Placa e frontend = ext (caixa-preta).
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

board: "EBAZ4205 (PS/PL) [fig. 01-03]\ntelemetria UDP ~100 kHz" {class: ext}

gw: "Gateway Go (cmd/gateway) - PC Host (software)" {
  class: grp

  ingest: Ingestao {
    class: dom
    recv: "Receiver UDP\n+ parse frames" {class: box}
    ring: "Ring buffer\n(lock-free)" {class: box}
    recv -> ring: {class: arrow}
  }

  proc: Processamento {
    class: dom
    derive: "Modelo do Motor\n-> T_e, abc (full-rate)" {class: box}
    pyramid: "Piramide de Tiles\n(decimacao de display, min/max)" {class: box}
    store: "Sessao + Captura\n(.hilbin, ~100 kHz)" {class: box}
    derive -> pyramid: {class: arrow}
    derive -> store: {class: arrow}
  }

  api: "API HTTP / SSE\n(/api  /events)" {class: box}

  ingest.ring -> proc.derive: {class: arrow}
  proc.pyramid -> api: tiles {class: arrow}
}

front: "Frontend (browser) [fig. 05]" {class: ext}

board -> gw.ingest.recv: "UDP ~100 kHz" {class: arrow}
gw.api -> front: "tiles (HTTP) + telemetria (SSE)" {class: arrow}
front -> gw.api: comandos {class: arrow; style.stroke-dash: 4}
```

- [ ] **Step 3: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 04-backend.d2 img/04-backend.png`
Expected: `success: successfully compiled 04-backend.d2 ...`

- [ ] **Step 4: Verificar visualmente**

Checklist: (a) ingestão + processamento + API internos; (b) pirâmide marca "decimacao de display"; (c) placa e frontend são `ext`.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add -A docs/diagrams/04-backend.d2 docs/diagrams/img/04-backend.png docs/diagrams/img/04-backend.svg
git commit -m "docs(diagramas): renumera backend para figura 04"
```

---

### Task 6: Figura 05 — Frontend

Renomeia `04-frontend.d2` → `05-frontend.d2`. Gateway como `ext`.

**Files:**
- Rename+Modify: `docs/diagrams/04-frontend.d2` → `docs/diagrams/05-frontend.d2`
- Delete (órfãos): `docs/diagrams/img/04-frontend.{svg,png}`
- Render: `docs/diagrams/img/05-frontend.{svg,png}`

- [ ] **Step 1: Renomear e remover órfãos**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/docs/diagrams
mv 04-frontend.d2 05-frontend.d2
rm -f img/04-frontend.svg img/04-frontend.png
```

- [ ] **Step 2: Substituir o conteúdo de `05-frontend.d2`**

```d2
# =============================================================================
# Figura 05 - Frontend (apps/hil-go/frontend). Gateway = ext (caixa-preta).
# =============================================================================

vars: {d2-config: {layout-engine: elk; pad: 40}}
direction: right

classes: {
  box:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  fast:  {style: {fill: "#d9d9d9"; stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false}}
  cdc:   {style: {fill: white;    stroke: black; stroke-width: 2; stroke-dash: 4; border-radius: 0; font-color: black; bold: false}}
  ext:   {style: {fill: white;    stroke: black; stroke-width: 2; border-radius: 0; font-color: black; bold: false; double-border: true}}
  grp:   {style: {fill: "#f2f2f2"; stroke: black; stroke-width: 2; stroke-dash: 6; border-radius: 0; font-color: black; bold: true}}
  dom:   {style: {fill: "#ececec"; stroke: black; stroke-width: 2; stroke-dash: 2; border-radius: 0; font-color: black; bold: true}}
  arrow: {style: {stroke: black; stroke-width: 2; font-color: black; bold: false}}
}

gw: "Gateway Go (HTTP / SSE) [fig. 04]" {class: ext}

app: "Frontend (TypeScript / uPlot) - PC Host (navegador)" {
  class: grp

  main: "main.ts\norquestrador da UI" {class: box}

  data: Camada de Dados {
    class: dom
    tile: "Tiles + Cache\n(decode)" {class: box}
    history: "Janela Historica" {class: box}
    tile -> history: {class: arrow}
  }

  view: Renderizacao {
    class: dom
    viewport: "Viewport\n(zoom / pan)" {class: box}
    sched: "Render Scheduler\n(throttle)" {class: box}
    uplot: "uPlot\n(canvas)" {class: box}
    viewport -> sched: {class: arrow}
    sched -> uplot: {class: arrow}
  }

  main -> data.tile: {class: arrow}
  main -> view.viewport: {class: arrow}
  data.tile -> view.uplot: series {class: arrow}
}

gw -> app.main: "telemetria ao vivo\n(SSE)" {class: arrow}
gw -> app.data.tile: "tiles por zoom\n(HTTP)" {class: arrow}
app.main -> gw: comandos {class: arrow; style.stroke-dash: 4}

legenda: "tracejado = comandos   |   solido = dados (telemetria/tiles)   |   borda dupla = caixa-preta" {
  near: bottom-center
  shape: text
  style: {font-color: black; font-size: 16}
}
```

- [ ] **Step 3: Renderizar**

Run: `cd docs/diagrams && export PATH="$HOME/.local/bin:$PATH" && d2 -t 0 -l elk 05-frontend.d2 img/05-frontend.png`
Expected: `success: successfully compiled 05-frontend.d2 ...`

- [ ] **Step 4: Verificar visualmente**

Checklist: (a) main + camada de dados + renderização internos; (b) gateway é `ext`.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add -A docs/diagrams/05-frontend.d2 docs/diagrams/img/05-frontend.png docs/diagrams/img/05-frontend.svg
git commit -m "docs(diagramas): renumera frontend para figura 05"
```

---

### Task 7: README + build completo + verificação final

Atualiza a tabela de figuras no `README.md` (6 figuras + regra de fronteira + convenção `ext`), roda o build completo e confirma que não há imagens órfãs.

**Files:**
- Modify: `docs/diagrams/README.md`
- Render: todos via `build.sh`

- [ ] **Step 1: Substituir a tabela de níveis no `README.md`**

Localizar a seção "## Níveis" (tabela atual de 5 linhas + imagem) e substituir por:

```markdown
## Figuras (leitura em ordem)

Cada figura documenta UM subsistema; vizinhos aparecem como caixa-preta (borda
dupla) rotulada com a interface. Lendo as 6 em ordem, o sistema fica explicado
do geral ao específico, sem nenhum bloco detalhado em dois lugares.

| Arquivo | Figura | Possui (detalha) |
|---|---|---|
| `00-system.d2`    | Mapa | Os 3 domínios (caixa-preta) + malha de controle + **cadeia de taxas fim-a-fim** |
| `01-fpga-top.d2`  | FPGA / HIL_AXI_Top | NPC, **domínios 100/200 MHz + CDC**, anti-aliasing, **decimador ÷77**, DMA |
| `02-solver.d2`    | TIM_Solver | Clarke, **bilinear A·X+B·U+Y(X·X)**, **Q14.28**, passo 130 ns, coeficientes |
| `03-ps-daemon.d2` | PS / daemon | Máquina de estados, V/F na ISR, DMA; **regimes ISR 1 kHz vs DMA 100 kHz** |
| `04-backend.d2`   | Backend Go | Ingestão UDP, derive, **pirâmide/decimação de display**, API HTTP/SSE |
| `05-frontend.d2`  | Frontend | main.ts, tiles/cache, viewport/zoom, render scheduler, uPlot |

![Mapa do sistema](img/00-system.png)

**Regra de fronteira:** cada conceito transversal é detalhado só no seu dono —
cadeia de taxas → 00; clocks/CDC/decimador → 01; Q14.28/passo → 02; regimes
temporais → 03; decimação de display → 04.
```

- [ ] **Step 2: Atualizar a tabela de convenções (adicionar `ext`)**

Na seção "## Estilo e convenções", adicionar a linha na tabela (após a linha "Caixa de borda tracejada | Travessia de clock (CDC)"):

```markdown
| Caixa de **borda dupla** | Vizinho em caixa-preta (detalhado na sua própria figura) |
```

- [ ] **Step 3: Build completo**

Run: `cd docs/diagrams && ./build.sh 2>&1 | grep -ciE success`
Expected: `12` (6 figuras × SVG+PNG)

- [ ] **Step 4: Confirmar ausência de órfãos**

Run: `cd docs/diagrams && ls img/ | sort`
Expected: exatamente `00-system`, `01-fpga-top`, `02-solver`, `03-ps-daemon`, `04-backend`, `05-frontend` (cada um `.png` e `.svg`); nenhum `01-solver*`, `02-ps-daemon*`, `03-backend*`, `04-frontend*`.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add -A docs/diagrams/README.md docs/diagrams/img
git commit -m "docs(diagramas): README com as 6 figuras, regra de fronteira e convencao ext"
```

---

## Self-Review

**1. Spec coverage:**
- 6 figuras (mapa + FPGA-Top + Solver + PS + Backend + Frontend) → Tasks 1-6. ✓
- Regra de fronteira (vizinho = `ext`) → classe `ext` nas Global Constraints, aplicada em todas. ✓
- Donos dos conceitos transversais → cadeia de taxas (T1), clocks/CDC/decimador (T2), Q14.28/passo (T3), regimes temporais (T4), decimação de display (T5). ✓
- Renumeração de arquivos → Tasks 2,4,5,6 (mv) + remoção de órfãos + T7 verifica. ✓
- README com 6 figuras + regra → Task 7. ✓
- Nota de implementação do spec (estrutura real do TIM_Solver) → resolvida: blocos da fig. 02 vêm de `src/rtl/TIM_Solver.vhd` (timer, Clarke, A/B shadow, Y, bilinear, X, mapeamento). ✓

**2. Placeholder scan:** sem TBD/TODO; todo `.d2` está completo e literal. ✓

**3. Type consistency:** nomes de interface de borda casam entre figuras vizinhas — `TIM_Solver` é `ext` na fig. 01 e `grp` detalhado na fig. 02; `V_a V_b V_c` e `I_ab psi_ab w` aparecem como saída/entrada coerentes entre 01 e 02; `Gateway Go` é `ext` em 03 e 05 e `grp` em 04; `HIL_AXI_Top` é `ext` em 03 e `grp` em 01. ✓
