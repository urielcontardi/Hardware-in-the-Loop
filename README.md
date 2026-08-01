# Hardware-in-the-Loop (HIL) — 3-Phase Induction Motor

FPGA-based Hardware-in-the-Loop simulation of a three-phase induction motor using NPC modulation and DMA/UDP telemetry, targeting the **EBAZ4205 (Zynq-7010)** board.

---

## Project Status

| Phase | Status | Notes |
|---|---|---|
| VHDL TIM_Solver (simulation) | **Done** | NRMSE currents e speed MAE dentro da tolerância — ver tabela abaixo |
| Flux error | **Em validação ativa** | Campanha em andamento, tolerância < 1 mWb — ver `verification/cocotb/reports/` |
| BilinearSolverUnit_DSP validation | **Pending** | Confirm stub == Xilinx IP behavior |
| Vivado project (EBAZ4205 base) | **Done** | PS7 + Ethernet EMIO + LEDs, Vivado 2025.1 |
| Linux boot (PetaLinux 2025.1) | **Done** | Kernel 6.12.10, SD card, UART console |
| HIL integration into BD | **Done** | NPCManager + TIM_Solver + AXI DMA |
| Linux control daemon | **Done** | V/F control and UDP telemetry |
| HIL Monitor | **Done** | Go gateway/Wails backend + TypeScript frontend |

---

## Project Structure

```
Hardware-in-the-Loop/
│
├── apps/                        # Desktop applications
│   └── hil-go/                 # Go gateway/Wails backend + TypeScript UI
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
├── scripts/                     # Host PC scripts (ver scripts/README.md)
│   ├── setup/                   # Instalação de dependências (PetaLinux, etc.)
│   ├── build/                   # Scripts de build Vivado/PetaLinux
│   ├── vivado/                  # Scripts auxiliares de Vivado
│   └── test/                    # Scripts de teste/validação (host)
│
├── src/                         # Source code
│   ├── rtl/                     # Hardware (VHDL)
│   │   ├── HIL_AXI_Top.vhd      # Top REAL de hardware (HIL_Regs_AXI + NPCManager + TIM_Solver + DMA)
│   │   ├── HIL_Regs_AXI.vhd     # Registradores AXI4-Lite (controle PS→PL)
│   │   ├── TIM_Solver.vhd       # Induction motor model
│   │   ├── Top_HIL.vhd          # Top-level de simulação (cocotb, usa SerialManager)
│   │   ├── SerialManager.vhd    # Protocolo UART — só usado por Top_HIL.vhd
│   │   ├── IIRFilter.vhd        # Presente no repo, não instanciado hoje
│   │   └── vf_control/          # V/F em hardware — não instanciado (V/F real roda em software, ver docs/architecture.md)
│   ├── ps_app/                  # Aplicação Linux do PS (main.c, vf_irq.c, dma_telem.c)
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

### Build reproduzível

```bash
# Validação de clone: RTL, Go, frontend e PS nativo
make

# Hardware completo: recria o projeto Vivado do TCL canônico,
# sintetiza/implementa e compila os binários ARM
make all-hardware
```

`make synth` sempre recria `syn/hil/ebaz4205/` a partir de
`create_ebaz4205_project.tcl`. O diretório `.xpr` é artefato descartável e nunca
é fonte do projeto.

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
  make synth               Recriar projeto + síntese + implementação + XSA
  make vivado-project      Apenas recriar o projeto gerado
  make vivado-clean        Remover projeto e XSA gerados
  make sim-dsp-compare     DSP stub vs IP Xilinx (xsim)
  make sim-bsu-compare     BSU solver stub vs IP (xsim)
  make sim-clarke          Clarke transform behavioural (xsim + VCD)
  make flash SD=/dev/sdX   Gravar SD card com imagens pré-compiladas

Aplicação HIL Monitor:
  make go-check            Testar e compilar gateway/backend Go
  make frontend-check      Instalar dependências e compilar frontend
  make ps-native-check     Compilar daemon PS para validação no host

Geral:
  make                     Validar RTL + Go + frontend + PS nativo
  make all-hardware        Validação host + Vivado + binários ARM
  make help                Exibir esta lista
  make clean               Remover todos os artefatos gerados
```

---

## Resultados de Validação (cocotb V/F ramp)

| Métrica | Tolerância | Status |
|---|---|---|
| NRMSE I_alpha | < 10% | OK |
| NRMSE I_beta | < 10% | OK |
| MAE flux_alpha | < 1 mWb | **Em validação ativa** |
| MAE flux_beta | < 1 mWb | **Em validação ativa** |
| MAE speed | < 2.0 rad/s | OK |

> Valores numéricos mudam a cada rodada da campanha em andamento — ver
> `verification/cocotb/reports/sim_benchmark.json` para o resultado mais recente.

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
| Go | conforme `apps/hil-go/go.mod` | Gateway e backend |
| Node.js + npm | versão LTS | Build do frontend |
| GCC / Make | toolchain do sistema | Validação nativa da aplicação PS |

As versões declaradas pelos manifests (`go.mod`, `package.json` e
`verification/cocotb/pyproject.toml`) prevalecem sobre esta tabela. O SDK do
PetaLinux é necessário apenas para os builds ARM.

---

## Convenções

- **VHDL entities**: `PascalCase` (ex: `TIM_Solver`)
- **VHDL files**: `PascalCase.vhd`
- **Python**: `snake_case.py`
- **Comentários no código**: inglês (documentação voltada ao usuário pode
  permanecer em português)
- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- **Branch principal**: `main`
- **Submódulo `common/`**: acompanha a revisão fixada pelo repositório raiz;
  não assuma que o `develop` mais recente é compatível
