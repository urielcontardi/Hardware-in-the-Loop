# PWM event capture architecture

This design captures PWM as transition events instead of streaming raw sampled
waveforms. It is intended to run automatically while the HIL is running.

## Goals

- Preserve PWM edge timing with FPGA-clock precision.
- Keep host bandwidth low by transmitting only state changes.
- Let the frontend reconstruct step waveforms later.
- Use a run-local time origin so PWM plots can share the HIL run timeline.

## Data path

```text
Run command
  -> vf_reset_solver()
  -> PWM enable rises in PL
  -> PL clears PWM event FIFO, resets run time, increments epoch
  -> PWM_Event_Capture records transitions while enable=1
  -> PS polls events over HIL_Regs_AXI
  -> PS sends UDP/JSON bursts to the host on port 5007
  -> gateway/Wails emits `pwm_events` to the frontend
  -> frontend reconstructs digital step traces
```

## PL event format

Each event is one 64-bit word:

```text
bits [31:0]  timestamp_cycles_low
bits [35:32] pwm_a state
bits [39:36] pwm_b state
bits [43:40] pwm_c state
bits [47:44] changed_mask
bits [63:48] epoch_id_low
```

`timestamp_cycles_low` is driven by a run-local counter in the 100 MHz PWM/AXI
clock domain. It resets when `pwm_enable` rises. With 32 bits at 100 MHz, the
visible timestamp wraps after about 42.9 s; long-run software must handle wrap
if the PWM trace is kept for longer than that.

`changed_mask` uses one bit per phase:

```text
bit0 = phase A changed
bit1 = phase B changed
bit2 = phase C changed
```

The frontend can ignore `changed_mask` and infer changes from consecutive
events, but the mask is useful for diagnostics.

## AXI register extension

The existing `HIL_Regs_AXI` map is extended beyond `0x3C`:

```text
0x40 PWM_CAP_CTRL          write
     bit0 = start/arm pulse
     bit1 = stop pulse
     bit2 = clear FIFO/status pulse

0x44 PWM_CAP_STATUS        read
     bit0 = active
     bit1 = overflow
     bit2 = fifo_empty
     bit3 = fifo_full
     bits[31:16] = event_count

0x48 PWM_CAP_WINDOW_CYCLES write/read
     0 = continuous while PWM enable is high
     N = stop after N clock cycles

0x4C PWM_CAP_DATA_LO       read
0x50 PWM_CAP_DATA_HI       read
0x54 PWM_CAP_POP           write bit0=1 pops the current event
```

The PS reads `STATUS`, then `DATA_LO/DATA_HI`, then writes `POP=1`.

## Frontend reconstruction

The frontend stores events as:

```ts
type PwmEvent = {
  tCycles: number;
  a: number;
  b: number;
  c: number;
  epoch: number;
};
```

For a plot window, it converts to seconds:

```ts
const t = event.tCycles / clockHz;
```

Then it reconstructs step traces by duplicating each state at the next event
time. The compact overview can show NPC phase states:

```text
"0011" -> +1
"1100" -> -1
other  ->  0
```

For gate-level inspection, the same event stream can be expanded into the
twelve individual switch bits: A1..A4, B1..B4, C1..C4.

## Alignment

PWM timestamps and HIL telemetry timestamps come from the same PL run-local
counter. The PS reads `hil_time`/`hil_epoch` from `HIL_Regs_AXI` when it samples
motor telemetry, and the frontend plots both streams with:

```ts
t_sec = t_cycles / clock_hz
```

This keeps PWM and HIL outputs aligned by hardware time instead of Linux, UDP,
Wails, browser scheduling, or packet arrival latency. If the capture is kept for
more than 42.9 s, frontend code must handle the 32-bit timestamp wrap.

