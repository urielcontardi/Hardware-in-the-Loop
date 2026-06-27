# Offline FPGA-vs-C comparison reports from .hilbin captures

**Date:** 2026-06-23
**Author:** Uriel Abe Contardi (with Claude)
**Status:** Approved (user delegated execution — "só me entrega os relatórios")

## Goal

Validate the real FPGA HIL solver against the C reference model (`IM_Model.c`,
same source that became the `TIM_Solver` VHDL) for the master's-thesis
validation chapter. Produce per-capture comparison **reports** (overlay plots +
error metrics) from the `.hilbin` captures already recorded in
`apps/hil-go/runs/`, with no live board required and no manual steps.

## Key discovery — most of this already exists

`verification/cocotb/` already implements FPGA-vs-C validation:

- `models/im_reference_model.py` — compiles `IM_Model.c` via `ctypes`
  (Python→C harness), Python fallback if no toolchain. Params match
  `TIM_Solver` generics.
- `scripts/fpga_vs_c.py` — drives the **live** board, captures telemetry + PWM,
  runs the C model with the same stimulus, computes metrics, writes HTML. Has a
  PWM-fed replay path (`run_c_model_pwm_fed`), cross-correlation alignment
  (`best_lag`), ripple low-pass (`lowpass`), metrics (`nrmse`, `mae`,
  `fundamental_amp`), and `make_report`.

The only gap: `fpga_vs_c.py` needs the **live board**. The captures are offline.

## Design

One new entry point, `verification/cocotb/scripts/hilbin_vs_c.py`, that sources
the FPGA trajectory and the PWM gate stream from a recorded `.hilbin` and reuses
everything else from `fpga_vs_c.py`.

### Why PWM replay (not re-deriving the V/F stimulus)

The `.hilbin` stores the actual PWM gate events. Replaying them through
`NPC_to_Voltage` (`0011→+Vdc/2`, `1100→−Vdc/2`, else `0`) feeds the C model the
*same switched voltage the FPGA solver integrated*, so the residual is purely
solver arithmetic/quantisation. This is self-contained in the capture — no need
to know the original V/F command (freq/accel), which is **not** stored.

### `.hilbin` format (confirmed from the Go recorder)

```
[0:7]   "HILDATA"
[7]     version (=1)
[8:12]  u32 LE  metaLen
[12:..] JSON metadata {version,date,name,sample_count,pwm_count,raw,clock_hz}
        → padded to 8-byte alignment
[pos]   u32 LE  sampleCount
        sampleCount × 28 bytes: 7×f32 LE = [t_s, ia, ib, flux_a, flux_b, speed, pad]
[..]    u32 LE  pwmCount
        pwmCount × 8 bytes: f32 t_s, u8 a, u8 b, u8 c, u8 pad
```

Sample `t` is re-based to the first sample; PWM `t` is absolute/clock. The
parser re-zeros both timelines and `best_lag` corrects residual phase.

### Fidelity contract (must match the FPGA exactly)

- Solver step `Ts = 26 / 200 MHz = 130 ns` (`TIMER_STEPS=26 @ 200 MHz`). The
  1 kHz figure is the V/F reference ZOH rate, **not** the solver step.
- `MODEL_A`, motor params = `TIM_Solver` generics (rs=0.4396, rr=0.2826,
  ls=3.1364e-3, lr=6.3264e-3, lm=109.9442e-3, J=0.4, npp=2), single source via
  `IMPhysicalParams.defaults()`.
- NPC encoding and `Vdc` (default 1240 V) from `vf_ctrl.c` / `fpga_vs_c.py`.

### Components

- `parse_hilbin(path) -> (meta, fpga_dict, pwm_dict)` — numpy parser.
- `run_one(path, vdc, tload, out_dir)` — parse → `run_c_model_pwm_fed` →
  `best_lag` align → steady-window metrics → `make_report` HTML + `metrics.json`.
- CLI: single file, or `--all` to batch `apps/hil-go/runs/*.hilbin`.

### Outputs

`verification/cocotb/reports/hilbin/<capture>/report.html` + `metrics.json`
(per-channel NRMSE for iα/iβ, MAE for ψα/ψβ/ωm, fundamental-amplitude Δ).

## Data caveat (not an FPGA change)

Load torque `Tload` is not in telemetry; defaults to 0 (the `vf_ctrl.c` default).
For load-step captures, pass the known value via CLI.

## Out of scope

- "Ideal voltage" layer (would need an RTL bypass mux). Deferred; PWM replay
  already isolates solver numerics since the input is identical on both sides.
- Live co-simulation (already covered by `fpga_vs_c.py`).

## Testing

- `parse_hilbin` round-trip on a small synthetic `.hilbin`.
- C-model-vs-itself sanity (≈0 error) to validate alignment.
- One real capture end-to-end producing a report.
