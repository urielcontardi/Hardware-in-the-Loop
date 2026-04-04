# Hardware-in-the-Loop (HIL) — 3-Phase Induction Motor

FPGA-based Hardware-in-the-Loop simulation of a Three-phase Induction Motor (TIM) using NPC modulation and UART-based monitoring, targeting the **EBAZ4205 (Zynq-7010)** board.

---

## Project Status

| Phase | Status | Notes |
|---|---|---|
| VHDL TIM_Solver (simulation) | **Done** | NRMSE currents < 3%, speed MAE < 0.7 rad/s |
| Flux error | **Pending fix** | MAE ~5.5 mWb, tolerance < 1 mWb |
| BilinearSolverUnit_DSP validation | **Next** | Confirm stub == Xilinx IP behavior |
| Synthesis + implementation (EBAZ4205) | **Next** | Vivado, Zynq-7010 |
| PS bare-metal firmware (V/F ramp) | **Next** | ARM writes va/vb/vc_ref via AXI GPIO |
| Board bring-up | **Todo** | Program bitstream, monitor UART |
| Tauri GUI integration | **Backlog** | `apps/hil-gui-tauri/` scaffold ready |

---

## Next Steps (POC Roadmap)

### Step 1 — Validate BilinearSolverUnit_DSP stub vs Xilinx IP

**Why this matters:** GHDL/NVC simulation uses `BilienarSolverUnit_DSP.vhd` (behavioral stub — pure registered `signed(A) * signed(B)`). Vivado synthesis uses the `mult_gen` IP (DSP48E1-based, 7-stage pipeline). If both produce the same output for the same inputs, the simulation results transfer directly to hardware.

**Approach:**
1. Create a Vivado simulation testbench (`tb_DSP_stub_vs_ip.vhd` in `syn/hil/`) that instantiates both entities side by side.
2. Drive identical random 42-bit input vectors (cover edge cases: zero, max, min, alternating signs).
3. Assert that `P_stub == P_ip` for every cycle after the 7-cycle pipeline drains.
4. Run in Vivado xsim: `launch_simulation` from the HIL_EBAZ4205 project.

The math guarantee: both are signed 42×42 → 84-bit integer multipliers with identical latency. A mismatch would only occur if the IP configuration (bit widths or pipeline depth) were wrong — which the testbench catches.

> See `common/modules/bilinear_solver/src/BilienarSolverUnit_DSP.vhd` (stub) and
> `common/modules/bilinear_solver/src/BilienarSolverUnit_DSP_real.vhd` (DSP48E1 manual impl, alternative reference).

---

### Step 2 — Synthesize bitstream for EBAZ4205

```bash
cd syn/hil

# Recreate Vivado project (erases any existing HIL_EBAZ4205/ first)
vivado -mode batch -source create_project.tcl

# Synthesize + implement + bitstream (from Vivado Tcl console or batch):
open_project HIL_EBAZ4205/HIL_EBAZ4205.xpr
launch_runs synth_1 -jobs 4
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
# Bitstream: HIL_EBAZ4205/HIL_EBAZ4205.runs/impl_1/Top_HIL_Zynq.bit
```

**What gets synthesized (`Top_HIL_Zynq.vhd`):**
```
PS7 (ARM Cortex-A9)
  └── AXI GPIO ──► va_ref / vb_ref / vc_ref / pwm_ctrl (to PL)

PL:
  NPCManager ◄── va/vb/vc_ref (from PS)
    └── NPC states ──► va/vb/vc_motor (combinational)

  TIM_Solver ◄── va/vb/vc_motor, torque_load
    └── ialpha/ibeta/flux_alpha/flux_beta/speed_mech

  SerialManager ◄──► UART J7 (F19/F20, 115200 baud)
```

> Constraints: `syn/hil/ebaz4205.xdc`
> Block design (PS7 + AXI GPIO): `syn/hil/zynq_ps7.tcl`

---

### Step 3 — PS bare-metal firmware (V/F ramp)

Write a bare-metal C application to run on the ARM PS7:

```c
// Pseudo-code — Vitis/SDK bare-metal
#include "xgpio.h"

// AXI GPIO address map (see zynq_ps7.tcl):
//   0x41200000  gpio_0: ch1=va_ref  ch2=vb_ref
//   0x41210000  gpio_1: ch1=vc_ref  ch2=pwm_ctrl

void vf_ramp_loop() {
    float freq = 0.0f;
    float t = 0.0f;

    while (1) {
        // V/F: ramp frequency 0..60 Hz over ~2 s
        freq = (freq < 60.0f) ? freq + RAMP_RATE * Ts : 60.0f;
        float v_peak = (freq / 60.0f) * V_NOMINAL;

        // Compute 3-phase references (Q14.28 fixed-point)
        int32_t va = fp_from_float(v_peak * sinf(2*PI*freq*t));
        int32_t vb = fp_from_float(v_peak * sinf(2*PI*freq*t - 2*PI/3));
        int32_t vc = fp_from_float(v_peak * sinf(2*PI*freq*t + 2*PI/3));

        // Write to PL via AXI GPIO
        XGpio_DiscreteWrite(&gpio0, 1, va);  // va_ref
        XGpio_DiscreteWrite(&gpio0, 2, vb);  // vb_ref
        XGpio_DiscreteWrite(&gpio1, 1, vc);  // vc_ref
        XGpio_DiscreteWrite(&gpio1, 2, 0x1); // pwm_ctrl: enable

        t += Ts;
        usleep(Ts_us);
    }
}
```

> Create this app in Vitis from the exported XSA (hardware platform from Vivado).

---

### Step 4 — Board bring-up

1. Program the bitstream: `program_hw_devices` in Vivado Hardware Manager (or `xsdb`).
2. Run the PS application (bare-metal via JTAG or standalone boot from SD card).
3. Connect a USB-UART to J7 (F19=TX, F20=RX, 115200 8N1).
4. Read motor state via the `SerialManager` protocol:
   ```
   'R' 0x09  →  0xAA 0x09 <speed_mech 6 bytes MSB-first>   (speed in rad/s, Q14.28)
   'A'        →  0x55 <all 10 registers>
   ```
5. Verify: current waveforms (ialpha/ibeta) should be sinusoidal at the V/F frequency; speed should ramp.

---

## Project Structure

```
Hardware-in-the-Loop/
├── src/rtl/
│   ├── Top_HIL_Zynq.vhd       # Top-level for EBAZ4205 (PS7 + NPC + TIM + UART)
│   ├── TIM_Solver.vhd          # 3-phase induction motor bilinear model (Q14.28)
│   ├── SerialManager.vhd       # UART register interface (10 regs, 42-bit)
│   └── vf_control/             # V/F open-loop controller (PL-side, optional)
│
├── common/                     # Shared VHDL modules (git submodule)
│   └── modules/
│       ├── bilinear_solver/    # Fixed-point bilinear integrator + DSP stub/IP
│       ├── clarke_transform/   # Clarke (abc → αβ) transform
│       ├── npc_modulator/      # NPC 3-level PWM modulator
│       └── uart/               # UART TX/RX
│
├── syn/
│   ├── hil/                    # EBAZ4205 HIL system synthesis
│   │   ├── create_project.tcl  # Recreates HIL_EBAZ4205.xpr from scratch
│   │   ├── zynq_ps7.tcl        # Block design: PS7 + AXI GPIO
│   │   └── ebaz4205.xdc        # Pin constraints
│   └── dut/                    # (reserved) standalone DUT synthesis
│
├── verification/cocotb/        # Python cocotb tests (GHDL/NVC)
│   ├── tests/                  # test_tim_solver_vf.py (main V/F validation)
│   ├── models/                 # C reference model wrapper
│   └── reports/                # HTML reports + sim_benchmark.json
│
└── apps/hil-gui-tauri/         # Desktop GUI scaffold (Tauri + Rust + TypeScript)
```

---

## Simulation Quick Start (VHDL verification — already done)

```bash
# Install NVC simulator (recommended for speed)
make setup-nvc

# Run full V/F validation (15 M steps, ~4.6 h on 28-core machine)
make cocotb-tim-vf

# Or run in background and check later
make tim-vf-bg

# Open last report
xdg-open verification/cocotb/reports/vf_report.html
```

Validation thresholds:

| Metric | Result | Tolerance | Status |
|---|---|---|---|
| NRMSE I_alpha | 2.85% | < 10% | OK |
| NRMSE I_beta | 2.89% | < 10% | OK |
| MAE flux_alpha | 5.49 mWb | < 1 mWb | **FAIL** |
| MAE flux_beta | 5.70 mWb | < 1 mWb | **FAIL** |
| MAE speed | 0.70 rad/s | < 2.0 rad/s | OK |

---

## SerialManager Protocol

| Addr | Register | Access | Format |
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

## License

See individual module headers for license information.
