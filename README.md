# Hardware-in-the-Loop (HIL) — 3-Phase Induction Motor

FPGA-based Hardware-in-the-Loop simulation of a Three-phase Induction Motor (TIM) using NPC modulation and UART-based monitoring.

## Project Structure

```
Hardware-in-the-Loop/
├── Makefile                    # Unified build system (VHDL + cocotb)
├── README.md
│
├── src/
│   ├── rtl/                    # Synthesizable VHDL
│   │   ├── Top_HIL.vhd        # Top-level: NPCManager + TIM_Solver + SerialManager
│   │   ├── SerialManager.vhd  # UART register interface (10 regs, 42-bit)
│   │   ├── TIM_Solver.vhd     # 3-phase induction motor bilinear model
│   │   └── vf_control/        # V/F open-loop controller (optional)
│   └── tb/                     # VHDL testbenches (GHDL)
│       ├── tb_SerialManager.vhd
│       ├── tb_TIMSolver.vhd
│       └── tb_TopHIL.vhd
│
├── verification/
│   └── cocotb/                 # Python-based testbenches (cocotb 2.x)
│       ├── drivers/            # Reusable UART & protocol drivers
│       │   ├── uart_driver.py
│       │   └── serial_manager_driver.py
│       ├── tests/              # cocotb test modules
│       │   └── test_top_hil.py
│       ├── run.py              # Python runner (cocotb_tools.runner)
│       ├── Makefile            # Convenience targets
│       └── pyproject.toml      # Dependencies (managed by uv)
│
├── common/                     # Shared VHDL modules (git submodule)
│   └── modules/
│       ├── bilinear_solver/    # Fixed-point bilinear integrator
│       ├── clarke_transform/   # Clarke (abc → αβ) transform
│       ├── npc_modulator/      # NPC 3-level PWM modulator
│       ├── uart/               # UART TX/RX/Full
│       ├── fifo/               # Async/Sync FIFO
│       └── edge_detector/      # Rising/falling edge detector
│
├── syn/                        # Synthesis project (Xilinx Vivado)
│   └── HIL.xpr
│
├── extras/                     # Notebooks & scripts
│   └── TIM.ipynb
│
└── build/                      # GHDL build artifacts (auto-generated)
```

## Quick Start

### Prerequisites

| Tool    | Version  | Purpose                        |
|---------|----------|--------------------------------|
| GHDL    | ≥ 4.0    | VHDL simulator (VPI support)   |
| GTKWave | any      | Waveform viewer (optional)     |
| uv      | ≥ 0.10   | Python package manager         |

**Install uv** (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### First-time Setup (cocotb)

```bash
make cocotb-setup       # Installs cocotb + dependencies in a venv
```

### Running Simulations

#### VHDL Testbenches (GHDL)

```bash
make sim-serial         # SerialManager testbench
make sim-tim            # TIM Solver testbench
make sim-top            # Top_HIL testbench
make sim-all            # All VHDL testbenches

make wave-serial        # Run + open GTKWave
```

#### cocotb (Python) Tests

```bash
make cocotb                                     # Run all cocotb tests
make cocotb TESTCASE=test_write_read_vdc_bus    # Run a single test
make cocotb-waves                               # Run + GHW waveform dump
```

Or directly from the cocotb directory:
```bash
cd verification/cocotb
uv run python run.py                            # All tests
uv run python run.py -k test_pwm_enable         # Single test
uv run python run.py --waves                    # With waveforms
```

### All Targets

```bash
make help               # Show all available targets
```

## cocotb Test Suite

| Test                            | Description                                |
|---------------------------------|--------------------------------------------|
| `test_write_read_vdc_bus`       | Write/read VDC_BUS register via UART       |
| `test_write_read_torque_load`   | Write/read TORQUE_LOAD register via UART   |
| `test_read_all_registers`       | Dump all 10 registers with Read All cmd    |
| `test_pwm_enable`               | Enable PWM and verify gate output activity |
| `test_full_chain_motor_outputs` | Full chain: config → PWM → TIM → readback  |

### Adding New Tests

1. Create a new test function in [verification/cocotb/tests/test_top_hil.py](verification/cocotb/tests/test_top_hil.py) decorated with `@cocotb.test()`
2. Use the existing `SerialManagerDriver` for UART communication
3. Run with `make cocotb TESTCASE=your_new_test`

### cocotb Drivers

The reusable drivers in `verification/cocotb/drivers/` can be imported in any test:

```python
from drivers.serial_manager_driver import SerialManagerDriver, RegAddr
from drivers.uart_driver import UartTxDriver, UartRxDriver
```

## Architecture

```
 UART RX ──► SerialManager ──► VDC_BUS / TORQUE_LOAD registers
                  │
                  ▼
 va/vb/vc_ref ──► NPCManager ──► PWM gates (3-level NPC)
                      │
                      ▼
                  TIM_Solver ──► ia, ib, flux_α, flux_β, speed
                      │
                      ▼
              SerialManager ──► UART TX (readback)
```

## Register Map (SerialManager)

| Addr | Name         | Access | Description                    |
|------|------------- |--------|--------------------------------|
| 0x00 | VDC_BUS      | R/W    | DC bus voltage                 |
| 0x01 | TORQUE_LOAD  | R/W    | Motor load torque              |
| 0x02 | VA_MOTOR     | R      | Phase A voltage (NPC output)   |
| 0x03 | VB_MOTOR     | R      | Phase B voltage                |
| 0x04 | VC_MOTOR     | R      | Phase C voltage                |
| 0x05 | I_ALPHA      | R      | Stator current α               |
| 0x06 | I_BETA       | R      | Stator current β               |
| 0x07 | FLUX_ALPHA   | R      | Stator flux α                  |
| 0x08 | FLUX_BETA    | R      | Stator flux β                  |
| 0x09 | SPEED_MECH   | R      | Mechanical speed               |

**Protocol:**
- Write: `'W'` (0x57) | ADDR | DATA (6 bytes, MSB first)
- Read:  `'R'` (0x52) | ADDR → response: `0xAA` | ADDR | DATA
- Read All: `'A'` (0x41) → response: `0x55` | REG0..REG9

## License

See individual module headers for license information.
