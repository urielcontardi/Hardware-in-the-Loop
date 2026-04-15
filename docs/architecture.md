# HIL Architecture — EBAZ4205 (Zynq-7010)

FPGA-based Hardware-in-the-Loop for three-phase induction motor (TIM) simulation.

---

## Table of Contents

1. [System Context](#1-system-context)
2. [PS/PL Integration Overview](#2-pspl-integration-overview)
3. [PS Software Architecture](#3-ps-software-architecture)
4. [PL Block Design](#4-pl-block-design)
5. [Verification Flow](#5-verification-flow)
6. [TIM_Solver Pipeline](#6-tim_solver-pipeline)
7. [NPC Modulator Pipeline](#7-npc-modulator-pipeline)
8. [Referências Rápidas](#8-referências-rápidas)

---

## 1. System Context

Visão de alto nível das interfaces externas do sistema.

```mermaid
flowchart TB
    subgraph USER["Usuário / Engenheiro"]
        GUI["Tauri GUI"]
        CON["Console UART"]
    end

    subgraph HIL["HIL System — EBAZ4205"]
        subgraph PS["PS — ARM Cortex-A9"]
            APP["Linux App"]
        end
        subgraph PL["PL — FPGA Fabric"]
            FPGA["NPCManager + TIM_Solver"]
        end
        DDR["DDR3 Ring Buffer"]
        APP <-->|"AXI GP0"| FPGA
        FPGA -->|"AXI4-Stream S2MM"| DDR
        DDR -->|"mmap"| APP
    end

    GUI -->|"UDP/JSON — port 5005"| APP
    CON <-->|"UART1 — MIO24/25"| PS
```

> **Plataforma:** PetaLinux 2025.1 / Kernel 6.12.10 — **Clock PL:** FCLK0 @ 150 MHz

---

## 2. PS/PL Integration Overview

Blocos instanciados no Vivado Block Design e mapa de comunicação AXI entre PS e PL.

```mermaid
flowchart TB
    subgraph PS_SIDE["PS — Zynq PS7"]
        ARM["ARM Cortex-A9"]
        PS7_PERI["PS7 Periféricos"]
    end

    subgraph AXI_BUS["AXI Interconnect GP0"]
        SC["AXI SmartConnect"]
    end

    subgraph GPIO_IN["AXI GPIO — Entradas"]
        G_VREF_AB["GPIO: va_ref, vb_ref"]
        G_VREF_C["GPIO: vc_ref, pwm_ctrl, decim"]
        G_VDC_TQ["GPIO: vdc, torque"]
    end

    subgraph GPIO_OUT["AXI GPIO — Monitoramento"]
        G_MON1["GPIO: i_alpha, i_beta"]
        G_MON2["GPIO: flux_alpha, flux_beta"]
        G_MON3["GPIO: speed_mech, data_valid"]
    end

    subgraph PL_LOGIC["HIL_AXI_Top — PL"]
        NPC_BLK["NPCManager"]
        TIM_BLK["TIM_Solver"]
    end

    DMA_BLK["AXI DMA"]

    ARM --> SC
    SC --> G_VREF_AB & G_VREF_C & G_VDC_TQ
    G_VREF_AB & G_VREF_C & G_VDC_TQ -->|"Q14.28 — 42 bit"| NPC_BLK
    NPC_BLK -->|"va / vb / vc"| TIM_BLK
    TIM_BLK -->|"i, flux, speed"| G_MON1 & G_MON2 & G_MON3
    G_MON1 & G_MON2 & G_MON3 --> SC
    TIM_BLK -->|"AXI4-Stream 256-bit"| DMA_BLK
    DMA_BLK --> PS7_PERI
```

**Mapa de registradores AXI GPIO:**

| Endereço      | Direção  | Sinais                        |
|---------------|----------|-------------------------------|
| `0x4120_0000` | PL → PS  | `i_alpha`, `i_beta`           |
| `0x4121_0000` | PL → PS  | `flux_alpha`, `flux_beta`     |
| `0x4122_0000` | PL → PS  | `speed_mech`, `data_valid`    |
| `0x4123_0000` | PS → PL  | `vdc_q31`, `torque_q31`       |
| `0x4124_0000` | PS → PL  | `va_ref`, `vb_ref`            |
| `0x4125_0000` | PS → PL  | `vc_ref`, `pwm_ctrl`, `decim` |

**Formato de palavra:** Q14.28 (42 bits) — 14 inteiros + 28 fracionários  
**Pacote DMA:** 256 bits = 5 × 42-bit + 86-bit pad  
**Taxa de saída TIM_Solver:** ~3.75 MHz (40 ciclos × 150 MHz)

---

## 3. PS Software Architecture

Fluxo de execução do software no ARM: inicialização, timer de 1 kHz e handler UDP.

```mermaid
flowchart TD
    BOOT["main()"] --> INIT["Inicialização<br/>(GPIO, V/F, UDP)"]
    INIT --> TIMER_SETUP["POSIX Timer — SIGRTMIN @ 1 kHz"]
    TIMER_SETUP --> LOOP["Event Loop — select()"]

    LOOP -->|"SIGRTMIN"| ISR
    LOOP -->|"UDP packet"| UDP_H

    subgraph ISR["Timer ISR — vf_tick() a cada 1 ms"]
        LOAD["Carrega parâmetros"] --> VF_RATIO["Calcula razão V/F"]
        VF_RATIO --> ANGLE["Integra ângulo θ"]
        ANGLE --> SINE_GEN["Gera senoides 3-fase"]
        SINE_GEN --> SCALE["Escala → Q31"]
        SCALE --> GPIO_WRITE["Escreve AXI GPIO"]
    end

    subgraph UDP_H["UDP Handler — port 5005"]
        RX_JSON["Parse JSON"] --> CMD_DISPATCH{"cmd?"}
        CMD_DISPATCH -->|"set"| CMD_SET["Atualiza parâmetros"]
        CMD_DISPATCH -->|"get"| CMD_GET["Lê monitores → resposta JSON"]
    end
```

**Parâmetros configuráveis via UDP:**

| Campo       | Descrição                        |
|-------------|----------------------------------|
| `freq_hz`   | Frequência de saída (0–60 Hz)    |
| `vdc_v`     | Tensão do barramento DC          |
| `torque`    | Carga de torque aplicada         |
| `enable`    | Liga/desliga o controlador       |
| `decim`     | Fator de decimação do DMA        |

**Geração senoidal (V/F):**
```
v_pu = Vnom · (f / f₀),  clamped a 1.0
θ[k] = θ[k-1] + 2π · f · Ts

va = A · sin(θ)
vb = A · sin(θ − 2π/3)
vc = A · sin(θ + 2π/3)
```

---

## 4. PL Block Design

Hierarquia interna do `HIL_AXI_Top.vhd` e módulos instanciados na fabric.

```mermaid
flowchart TB
    subgraph HILAX["HIL_AXI_Top"]
        subgraph NPC_MGR["NPCManager"]
            NMOD["NPC Modulator ×3"] --> NDRV["NPC Gate Driver ×3"]
        end

        NPC2V["Decodificador de Nível"]

        subgraph TIM_S["TIM_Solver"]
            CLK_T["Clarke Transform"] --> BIL["BilinearSolverHandler"]
        end

        STREAM["Saída AXI4-Stream 256-bit"]
    end

    NDRV -->|"gate_states 4-bit × 3"| NPC2V
    NPC2V -->|"va / vb / vc — Q14.28"| CLK_T
    BIL -->|"data_valid"| STREAM
```

**Decodificação de nível NPC:**

| `gate[3:0]` | Tensão de saída |
|-------------|-----------------|
| `0011`      | `+Vdc/2`        |
| `0110`      | `0 V`           |
| `1100`      | `−Vdc/2`        |

**Módulos do `common/` (submodule):**

| Módulo                   | Arquivo                                     | Função                              |
|--------------------------|---------------------------------------------|-------------------------------------|
| `NPCModulator`           | `npc_modulator/NPCModulator.vhd`            | Comparador carrier vs. referência   |
| `NPCGateDriver`          | `npc_modulator/NPCGateDriver.vhd`           | Transições seguras + dead time      |
| `BilinearSolverUnit_DSP` | `bilinear_solver/BilinearSolverUnit_DSP.vhd`| Multiplicador 42×42 em DSP48E1      |
| `BilinearSolverHandler`  | `bilinear_solver/BilinearSolverHandler.vhd` | Orquestra cálculo linha-por-linha   |
| `ClarkeTransform`        | `clarke_transform/ClarkeTransform.vhd`      | abc → αβ (escala 2/3)              |

---

## 5. Verification Flow

Pipeline de verificação — do `make` até o relatório HTML.

```mermaid
flowchart TD
    DEV["Desenvolvedor"]

    subgraph MAKE_T["Makefile Targets"]
        T1["cocotb-tim-ref<br/>DC step — rápido"]
        T2["cocotb-tim-sine<br/>60 Hz senoidal — ~30 s"]
        T3["cocotb-tim-vf<br/>rampa V/F 0→60 Hz — ~4.6 h"]
    end

    subgraph SIM_ENV["Ambiente de Simulação"]
        COCOTB_PY["cocotb — Python"]
        SIM["GHDL / NVC"]
        DUT["VHDL DUT — Top_HIL.vhd"]
        COCOTB_PY <-->|"VHPI"| SIM
        SIM <--> DUT
    end

    subgraph REF_M["Modelo de Referência"]
        C_MODEL["C Reference Model"]
        PY_MODEL["Python fallback"]
        C_MODEL -.->|"se gcc indisponível"| PY_MODEL
    end

    REPORT["HTML Report + sim_benchmark.json"]

    DEV --> MAKE_T --> COCOTB_PY
    COCOTB_PY --> C_MODEL
    COCOTB_PY --> REPORT
```

**Métricas de validação (rampa V/F):**

| Sinal              | Limiar    | Status | Valor atual |
|--------------------|-----------|--------|-------------|
| NRMSE `i_α`, `i_β` | < 10%     | PASS   | ~2.87%      |
| MAE `flux_α/β`     | < 1 mWb   | FAIL   | ~5.5 mWb    |
| MAE `speed_mech`   | < 2 rad/s | PASS   | ~0.70 rad/s |

> **Simuladores suportados:** GHDL ≥ 4.0 · NVC ≥ 1.19.3

---

## 6. TIM_Solver Pipeline

Fluxo de dados interno do `TIM_Solver.vhd` — das tensões de fase às variáveis de estado do motor.

```mermaid
flowchart LR
    subgraph IN["Entradas — Q14.28"]
        VA["va_i"] & VB["vb_i"] & VC["vc_i"]
        TQ["torque_load_i"]
    end

    subgraph CLARKE["Clarke Transform"]
        CK["abc → αβ"]
    end

    subgraph SOLVER["BilinearSolverHandler<br/>40 ciclos @ 150 MHz"]
        EQ["x_next = A·x + A_bil·(x⊗y) + B·u"]
        DSP["DSP48E1 — 42×42 bit"]
        EQ --> DSP
    end

    subgraph STATE["Estado x[k]"]
        S1["flux_α, flux_β"]
        S2["i_α, i_β"]
        S3["ω_mech"]
    end

    subgraph OUT["Saídas — data_valid"]
        OI["i_alpha_o, i_beta_o"]
        OF["flux_rotor_alpha_o, flux_rotor_beta_o"]
        OS["speed_mech_o"]
    end

    VA & VB & VC --> CK
    CK -->|"vα, vβ"| SOLVER
    TQ --> SOLVER
    STATE -->|"feedback"| SOLVER
    SOLVER -->|"x[k+1]"| STATE
    SOLVER --> OI & OF & OS
```

**Equação de estado (bilinear):**
```
x[k+1] = A · x[k]  +  A_bil · (x[k] ⊗ y[k])  +  B · u[k]

x = [flux_α, flux_β, i_α, i_β, ω_mech]ᵀ   (5 estados)
u = [vα, vβ, torque_load]ᵀ
y = produto bilinear (acoplamento eletromagnético)
```

**Timing:** 40 ciclos × (1/150 MHz) ≈ 266 ns/passo → taxa máxima ~3.75 MHz

**Parâmetros do motor (0.75 kW, 4 polos):**

| Parâmetro | Símbolo | Valor         |
|-----------|---------|---------------|
| Resistência stator  | Rs  | 0.435 Ω       |
| Resistência rotor   | Rr  | 0.2826 Ω      |
| Indutância stator   | Ls  | 3.1364 mH     |
| Indutância rotor    | Lr  | 6.3264 mH     |
| Indutância mútua    | Lm  | 109.9442 mH   |
| Inércia             | J   | 0.192 kg·m²   |
| Pares de polos      | Npp | 2             |

---

## 7. NPC Modulator Pipeline

Fluxo interno do `NPCManager` — da referência de tensão até a tensão física aplicada ao motor.

```mermaid
flowchart TD
    subgraph REF_IN["Referências de Tensão — AXI GPIO"]
        RA["va_ref"] & RB["vb_ref"] & RC["vc_ref"]
    end

    subgraph CARRIER["Gerador de Carrier"]
        TRI["Contador triangular<br/>0 ↔ CARRIER_MAX"]
    end

    subgraph MODULATOR["NPC Modulator — ×3 fases"]
        C1["S1: ref > +carrier → superior"]
        C2["S2: ref > 0        → médio+"]
        C3["S3: ref < 0        → médio−"]
        C4["S4: ref < −carrier → inferior"]
    end

    subgraph GATE_DRV["NPC Gate Driver — ×3 fases"]
        SM2["State Machine"] --> DT["Dead time"]
        DT --> FLT["Fault detection"]
    end

    subgraph DECODE["Decodificação de Nível"]
        GL1["0011 → +Vdc/2"]
        GL2["0110 →  0 V"]
        GL3["1100 → −Vdc/2"]
    end

    subgraph VOLT_OUT["Tensões Físicas → TIM_Solver"]
        VO_A["va"] & VO_B["vb"] & VO_C["vc"]
    end

    RA & RB & RC --> MODULATOR
    TRI -->|"carrier"| MODULATOR
    MODULATOR --> SM2
    FLT -->|"gate_states 4-bit"| GL1 & GL2 & GL3
    GL1 & GL2 & GL3 --> VO_A & VO_B & VO_C
```

**Parâmetros do carrier:**

| Parâmetro      | Valor                           |
|----------------|---------------------------------|
| `CARRIER_MAX`  | 75 000                          |
| Frequência     | 150 MHz / (75 000 × 2) = 1 kHz  |
| 100% modulação | ±75 000                         |
| Uso típico     | ±63 750 (≈ 85%)                 |

---

## 8. Referências Rápidas

| Caminho                              | Conteúdo                                   |
|--------------------------------------|--------------------------------------------|
| `src/rtl/HIL_AXI_Top.vhd`           | Wrapper PL com AXI GPIO + DMA              |
| `src/rtl/Top_HIL.vhd`               | Top para simulação (com SerialManager)     |
| `src/rtl/TIM_Solver.vhd`            | Modelo do motor de indução                 |
| `src/ps_app/main.c`                  | Aplicação Linux (event loop, UDP, timer)   |
| `src/ps_app/vf_ctrl.c`              | Controlador V/F                            |
| `common/modules/npc_modulator/`      | NPCManager, NPCModulator, NPCGateDriver    |
| `common/modules/bilinear_solver/`    | BilinearSolverHandler, DSP48E1 wrapper     |
| `common/modules/clarke_transform/`   | ClarkeTransform                            |
| `syn/hil/create_ebaz4205_project.tcl`| Script Vivado BD (PS7, AXI GPIO, DMA)      |
| `verification/cocotb/`               | Testes cocotb + modelo de referência C/Py  |
