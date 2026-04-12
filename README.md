# Hardware-in-the-Loop (HIL) — 3-Phase Induction Motor

FPGA-based Hardware-in-the-Loop simulation of a Three-phase Induction Motor (TIM) using NPC modulation and UART-based monitoring, targeting the **EBAZ4205 (Zynq-7010)** board.

---

## Project Status

| Phase | Status | Notes |
|---|---|---|
| VHDL TIM_Solver (simulation) | **Done** | NRMSE currents < 3%, speed MAE < 0.7 rad/s |
| Flux error | **Pending fix** | MAE ~5.5 mWb, tolerance < 1 mWb |
| BilinearSolverUnit_DSP validation | **Pending** | Confirm stub == Xilinx IP behavior |
| Vivado project (EBAZ4205 base) | **Done** | PS7 + Ethernet EMIO + LEDs, Vivado 2025.1 |
| Linux boot (PetaLinux 2025.1) | **Done** | Kernel 6.12.10, SD card, UART console |
| HIL integration into BD | **Next** | Add NPCManager + TIM_Solver to Block Design |
| Linux app (V/F ramp via AXI) | **Next** | ARM writes va/vb/vc_ref to PL via AXI GPIO |
| Tauri GUI integration | **Backlog** | `apps/hil-gui-tauri/` scaffold ready |

---

## Project Structure

```
Hardware-in-the-Loop/
│
├── apps/                        # Desktop applications
│   └── hil-gui-tauri/          # Tauri GUI (Rust + TypeScript)
│
├── common/                      # Shared VHDL modules (git submodule)
│   └── modules/
│       ├── bilinear_solver/     # 42×42 signed multiplier (DSP48E1)
│       ├── clarke_transform/    # abc → αβ transformation
│       ├── npc_modulator/       # 3-level NPC PWM + gate driver
│       ├── uart/                # UART TX/RX
│       └── fifo/                # Async/sync FIFO
│
├── extras/                      # Reference material
│   ├── induction-motor-model/   # C reference model + PSIM files
│   └── longovinicius-hil/       # Legacy reference project
│
├── scripts/                     # Host PC scripts
│   └── setup/
│       └── install_petalinux_deps.sh  # PetaLinux dependencies
│
├── src/                         # Source code
│   ├── rtl/                     # Hardware (VHDL)
│   │   ├── TIM_Solver.vhd       # Induction motor model
│   │   ├── SerialManager.vhd    # UART protocol handler
│   │   ├── Top_HIL.vhd          # Top-level (used in cocotb simulation)
│   │   └── vf_control/          # V/F controller modules
│   └── tb/                      # VHDL testbenches
│
├── syn/                         # Synthesis and implementation
│   └── hil/                     # EBAZ4205 Vivado + PetaLinux project
│       ├── create_ebaz4205_project.tcl   # Recreates Vivado project from scratch
│       ├── run_impl_export.tcl           # Synth + impl + export XSA
│       ├── ebaz4205_board.xdc            # Pinout constraints
│       ├── flash_sd.sh                   # SD card programmer
│       ├── sd_images/                    # Pre-built boot images (ready to flash)
│       ├── ebaz4205_petalinux/           # PetaLinux project
│       └── README.md                     # Detailed FPGA/Linux workflow
│
└── verification/
    └── cocotb/                   # Python testbench framework
        ├── tests/                # Test modules
        ├── models/               # C reference model wrapper
        ├── drivers/              # cocotb drivers (UART, SerialManager)
        └── reports/              # Generated HTML reports
```

---

## Quick Start

### Simulation (GHDL + cocotb)

```bash
# Ver todos os targets disponíveis
make help

# Simular TIM_Solver com estímulo V/F (longo — ~4.6h em 28 cores)
make cocotb-tim-vf

# Teste rápido (60 Hz senoidal)
make cocotb-tim-sine

# Abrir relatório
xdg-open verification/cocotb/reports/vf_report.html
```

### FPGA (Vivado 2025.1)

```bash
# Criar projeto Vivado do zero
make vivado-project

# Sintetizar + implementar + exportar XSA
make synth
```

### SD Card (boot Linux na EBAZ4205)

```bash
# Flash direto com imagens pré-compiladas
make flash SD=/dev/sda

# Ou manualmente
sudo syn/hil/flash_sd.sh /dev/sda
```

> Ver `syn/hil/README.md` para o workflow completo (build PetaLinux do zero, atualizar bitstream, etc.)

### Console serial

```bash
picocom -b 115200 /dev/ttyUSB0
# Login: petalinux
# Sair: Ctrl+A → Ctrl+X
```

---

## Makefile — Targets disponíveis

```
Simulação VHDL (GHDL):
  make sim-serial          SerialManager testbench
  make sim-tim             TIM_Solver testbench
  make sim-top             Top_HIL testbench
  make sim-all             Todos os testbenches VHDL
  make wave-serial         SerialManager + GTKWave
  make wave-tim            TIM_Solver + GTKWave
  make wave-top            Top_HIL + GTKWave
  make compile             Analisa todos os fontes VHDL (sem simular)

cocotb (Python):
  make cocotb              Todos os testes
  make cocotb-tim-ref      TIM_Solver vs modelo C (entradas DC)
  make cocotb-tim-vf       V/F ramp (foreground, ~4.6h)
  make cocotb-tim-vf-bg    V/F ramp (background, monitor no terminal)
  make cocotb-tim-sine     60 Hz senoidal (rápido)
  make cocotb-waves        Testes + dump de formas de onda
  make cocotb-report       Gerar relatório HTML (modelo C)
  make cocotb-report-overlay  Relatório com overlay VHDL vs C
  make cocotb-report-sine  Relatório do teste senoidal
  make cocotb-setup        Instalar dependências Python (uv)
  make cocotb-setup-nvc    Instalar simulador NVC (mais rápido que GHDL)

Vivado / EBAZ4205:
  make vivado-project      Criar projeto ebaz4205.xpr do zero
  make synth               Síntese + implementação + exportar XSA
  make sim-dsp-compare     DSP stub vs IP Xilinx (xsim)
  make sim-bsu-compare     BSU solver stub vs IP (xsim)
  make sim-clarke          Clarke transform behavioural (xsim + VCD)
  make flash SD=/dev/sdX   Gravar SD card com imagens pré-compiladas

GUI Tauri (apps/hil-gui-tauri/):
  make gui-setup           Instalar dependências npm
  make gui-check           Build frontend + cargo check
  make gui-dev             Rodar GUI em modo desenvolvimento
  make gui-build           Build completo (Tauri)
  make gui-build-linux     Gerar pacotes .deb/.rpm

Geral:
  make help                Exibir esta lista
  make clean               Remover todos os artefatos gerados
```

---

## Resultados de Validação (cocotb V/F ramp)

| Métrica | Resultado | Tolerância | Status |
|---|---|---|---|
| NRMSE I_alpha | 2.85% | < 10% | OK |
| NRMSE I_beta | 2.89% | < 10% | OK |
| MAE flux_alpha | 5.49 mWb | < 1 mWb | **Pendente** |
| MAE flux_beta | 5.70 mWb | < 1 mWb | **Pendente** |
| MAE speed | 0.70 rad/s | < 2.0 rad/s | OK |

---

## SerialManager Protocol

| Addr | Registrador | Acesso | Formato |
|---|---|---|---|
| 0x00 | VDC_BUS | R/W | Q14.28, 42-bit |
| 0x01 | TORQUE_LOAD | R/W | Q14.28, 42-bit |
| 0x02–0x04 | VA/VB/VC_MOTOR | R | Q14.28, 42-bit |
| 0x05–0x06 | I_ALPHA / I_BETA | R | Q14.28, 42-bit |
| 0x07–0x08 | FLUX_ALPHA/BETA | R | Q14.28, 42-bit |
| 0x09 | SPEED_MECH | R | Q14.28, 42-bit (rad/s) |

```
Write:    'W' | ADDR(1B) | DATA(6B MSB-first)
Read:     'R' | ADDR(1B)  →  0xAA | ADDR | DATA(6B)
Read All: 'A'             →  0x55 | REG0..REG9 (60 bytes)
```

---

## Dependências

| Ferramenta | Versão | Uso |
|---|---|---|
| Vivado | 2025.1 | Síntese FPGA |
| PetaLinux | 2025.1 | Build Linux embarcado |
| GHDL | ≥ 4.0 | Simulação VHDL |
| NVC | ≥ 1.19.3 | Simulação VHDL (mais rápido) |
| Python | ≥ 3.10 | cocotb, modelos de referência |
| uv | latest | Gerenciador de pacotes Python |

---

## Convenções

- **VHDL entities**: `PascalCase` (ex: `TIM_Solver`)
- **VHDL files**: `PascalCase.vhd`
- **Python**: `snake_case.py`
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- **Branch principal**: `lcapyIntroduction` / desenvolvimento: `develop`
