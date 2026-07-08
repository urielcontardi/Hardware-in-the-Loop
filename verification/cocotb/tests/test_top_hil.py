"""
cocotb Testbench for Top_HIL module.

Tests the full HIL chain:
  1. UART Write → SerialManager → VDC bus / Torque load configuration
  2. UART Read  → SerialManager → Read back config & monitor registers
  3. PWM generation via NPCManager with voltage references
  4. NPC state → Voltage conversion feeding TIM_Solver
  5. TIM_Solver motor model outputs (currents, fluxes, speed)

Run with:
    cd verification/cocotb && make
"""

import math
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ClockCycles

from models.transient_metrics import compute_transient_metrics
from drivers.serial_manager_driver import (
    SerialManagerDriver,
    RegAddr,
    RSP_SINGLE,
    RSP_ALL,
)

# ═══════════════════════════════════════════════════════════════════════
#  Constants (must match Top_HIL generics for the cocotb Makefile)
# ═══════════════════════════════════════════════════════════════════════
CLK_FREQ         = 100_000_000       # 100 MHz (faster sim than 200 MHz)
BAUD_RATE        = 1_000_000         # 1 Mbaud (accelerate UART in sim)
PWM_FREQ         = 20_000            # 20 kHz switching frequency
DATA_WIDTH       = 42
NPC_DATA_WIDTH   = 32
CLK_PERIOD_NS    = int(1e9 / CLK_FREQ)
CARRIER_MAX      = CLK_FREQ // PWM_FREQ // 2  # 2500 — max reference amplitude
FP_FRACTION_BITS = 28                # Q14.28 fixed-point format


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════
def signed_to_slv(value: int, width: int) -> int:
    """Convert a signed Python int to unsigned representation for SLV assignment."""
    if value < 0:
        return value + (1 << width)
    return value


def slv_to_signed(value: int, width: int) -> int:
    """Convert unsigned SLV readback to signed Python int."""
    if value & (1 << (width - 1)):
        return value - (1 << width)
    return value


def real_to_fp(value: float) -> int:
    """Convert a real number to Q14.28 fixed-point integer (round-to-nearest)."""
    return int(round(value * (1 << FP_FRACTION_BITS)))


def fp_to_real(value: int, width: int = DATA_WIDTH) -> float:
    """Convert Q14.28 fixed-point (unsigned SLV) to real number."""
    signed_val = slv_to_signed(value, width)
    return signed_val / (1 << FP_FRACTION_BITS)


async def reset_dut(dut, cycles: int = 20):
    """Assert active-low reset for the given number of clock cycles."""
    dut.reset_n.value = 0
    dut.pwm_enb_i.value = 0
    dut.pwm_clear_i.value = 0
    dut.va_ref_i.value = 0
    dut.vb_ref_i.value = 0
    dut.vc_ref_i.value = 0
    dut.uart_rx_i.value = 1  # UART idle high
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_n.value = 1
    await ClockCycles(dut.clk_i, 5)


def create_serial_driver(dut) -> SerialManagerDriver:
    """Create a SerialManagerDriver wired to the DUT."""
    return SerialManagerDriver(
        rx_pin=dut.uart_rx_i,
        tx_pin=dut.uart_tx_o,
        clk=dut.clk_i,
        baud_rate=BAUD_RATE,
        clk_freq=CLK_FREQ,
        data_width=DATA_WIDTH,
    )


# ═══════════════════════════════════════════════════════════════════════
#  TEST 1: Write & readback VDC_BUS via UART
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_write_read_vdc_bus(dut):
    """Write VDC_BUS register via UART, then read it back and verify."""
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)
    vdc_value = 0xABCD

    # Write
    dut._log.info(f"Writing VDC_BUS = 0x{vdc_value:X}")
    await sm.set_vdc_bus(vdc_value)
    await ClockCycles(dut.clk_i, 50)

    # Read back
    resp = await sm.get_vdc_bus()
    dut._log.info(f"Readback: header=0x{resp.header:02X}, addr=0x{resp.address:02X}, value=0x{resp.value:X}")

    assert resp.header == RSP_SINGLE, f"Header mismatch: 0x{resp.header:02X}"
    assert resp.address == RegAddr.VDC_BUS, f"Addr mismatch: 0x{resp.address:02X}"
    # Mask to DATA_WIDTH bits
    mask = (1 << DATA_WIDTH) - 1
    assert (resp.value & mask) == (vdc_value & mask), \
        f"VDC_BUS mismatch: got 0x{resp.value & mask:X}, expected 0x{vdc_value & mask:X}"


# ═══════════════════════════════════════════════════════════════════════
#  TEST 2: Write & readback TORQUE_LOAD via UART
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_write_read_torque_load(dut):
    """Write TORQUE_LOAD register via UART, then read it back."""
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)
    torque_value = 0x1234

    await sm.set_torque_load(torque_value)
    await ClockCycles(dut.clk_i, 50)

    resp = await sm.get_torque_load()
    dut._log.info(f"TORQUE_LOAD readback: 0x{resp.value:X}")

    mask = (1 << DATA_WIDTH) - 1
    assert resp.header == RSP_SINGLE
    assert resp.address == RegAddr.TORQUE_LOAD
    assert (resp.value & mask) == (torque_value & mask)


# ═══════════════════════════════════════════════════════════════════════
#  TEST 3: Read All registers
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_read_all_registers(dut):
    """Write config registers, then use Read All to dump all 10 registers."""
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)

    # Write known values
    vdc_val = 0x0000FF
    tor_val = 0x000055
    await sm.set_vdc_bus(vdc_val)
    await ClockCycles(dut.clk_i, 20)
    await sm.set_torque_load(tor_val)
    await ClockCycles(dut.clk_i, 20)

    # Read All
    resp = await sm.read_all()
    dut._log.info(f"Read All header: 0x{resp.header:02X}")
    for addr, val in resp.registers.items():
        name = RegAddr.NAMES.get(addr, f"REG_{addr}")
        dut._log.info(f"  {name} (0x{addr:02X}) = 0x{val:012X} ({resp.signed_value(addr):d})")

    assert resp.header == RSP_ALL, f"Expected 0x55, got 0x{resp.header:02X}"
    mask = (1 << DATA_WIDTH) - 1
    assert (resp.registers[RegAddr.VDC_BUS] & mask) == (vdc_val & mask)
    assert (resp.registers[RegAddr.TORQUE_LOAD] & mask) == (tor_val & mask)


# ═══════════════════════════════════════════════════════════════════════
#  TEST 4: PWM enable and gate output activity
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_pwm_enable(dut):
    """Enable PWM with balanced 3-phase references and verify gate outputs become active.

    Key requirements for NPCGateDriver safe-startup:
    1. en_sync must be '1' (latched from pwm_enb_i at carrier valley tick)
    2. All 3 phases must see a transition TO the ZERO state ("01")
    3. |ref| must be < CARRIER_MAX so the modulator produces switching
       (at CARRIER_MAX the carrier never reaches |ref| → permanently active)
    """
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)

    # Configure VDC bus (300 V in Q14.28 fixed-point)
    await sm.set_vdc_bus(real_to_fp(300.0))
    await ClockCycles(dut.clk_i, 20)

    # Balanced 3-phase at θ=0° (Va at positive peak): va=Vm, vb=vc=-Vm/2.
    # All |ref| < CARRIER_MAX (2500) so the carrier always crosses |ref| →
    # ZERO state transitions occur every PWM cycle → NPCGateDriver startup condition met.
    ref = CARRIER_MAX * 85 // 100  # 2125 (85% modulation)
    va_ref =  ref          # +2125
    vb_ref = -(ref // 2)   # -1062  (= Vm·cos(−120°) = −Vm/2)
    vc_ref = -(ref // 2)   # -1062  (= Vm·cos(−240°) = −Vm/2)
    dut.va_ref_i.value = signed_to_slv(va_ref, NPC_DATA_WIDTH)
    dut.vb_ref_i.value = signed_to_slv(vb_ref, NPC_DATA_WIDTH)
    dut.vc_ref_i.value = signed_to_slv(vc_ref, NPC_DATA_WIDTH)
    dut._log.info(f"3-phase refs: va={va_ref}  vb={vb_ref}  vc={vc_ref}  (sum={va_ref+vb_ref+vc_ref})")

    # Enable PWM
    dut.pwm_enb_i.value = 1
    dut.pwm_clear_i.value = 0

    # Wait for:
    #  - 1st carrier valley (~5000 clk): refs sampled, en_sync latched
    #  - 1st carrier peak   (~7500 clk): modulator output crosses ZERO → gate driver starts
    #  - A few more PWM periods for all 3 phases to stabilize
    await ClockCycles(dut.clk_i, 50_000)  # 10 PWM periods = 0.5 ms

    # Check that pwm_on_o went high (all 3 gate drivers active)
    pwm_on = int(dut.pwm_on_o.value)
    dut._log.info(f"pwm_on_o = {pwm_on}")
    assert pwm_on == 1, "PWM should be active after enable with balanced refs"

    # Check that at least one gate output is non-zero (switching is happening)
    pwm_a = int(dut.pwm_a_o.value)
    pwm_b = int(dut.pwm_b_o.value)
    pwm_c = int(dut.pwm_c_o.value)
    dut._log.info(f"pwm_a_o=0b{pwm_a:04b}  pwm_b_o=0b{pwm_b:04b}  pwm_c_o=0b{pwm_c:04b}")
    assert (pwm_a | pwm_b | pwm_c) != 0, \
        "All gate outputs are zero — NPC modulator not switching"


# ═══════════════════════════════════════════════════════════════════════
#  TEST 5: Full chain – Configure VDC + enable PWM + read motor outputs
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_full_chain_motor_outputs(dut):
    """
    Full integration test:
    1. Configure VDC_BUS and TORQUE_LOAD via UART (proper Q14.28 encoding)
    2. Apply balanced voltage references within CARRIER_MAX range
    3. Enable PWM → gate drivers start → NPC→voltage conversion → TIM_Solver
    4. Wait for solver to accumulate non-zero outputs
    5. Read motor state via UART Read All and verify non-zero outputs
    """
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)

    # ── Step 1: Configure via UART (Q14.28 fixed-point) ────────────
    vdc_bus_volts = 300.0     # 300 V DC bus
    torque_nm     = 0.0       # No load
    vdc_bus_fp    = real_to_fp(vdc_bus_volts)
    torque_fp     = real_to_fp(torque_nm)

    await sm.set_vdc_bus(vdc_bus_fp)
    await ClockCycles(dut.clk_i, 20)
    await sm.set_torque_load(torque_fp)
    await ClockCycles(dut.clk_i, 20)

    # ── Step 2: Apply balanced 3-phase refs within CARRIER_MAX ──────
    # Balanced at θ=0°: va=Vm, vb=vc=-Vm/2.  All |ref| < CARRIER_MAX.
    ref = CARRIER_MAX * 85 // 100  # 2125 (85% modulation)
    va_ref =  ref          # +2125
    vb_ref = -(ref // 2)   # -1062
    vc_ref = -(ref // 2)   # -1062
    dut.va_ref_i.value = signed_to_slv(va_ref, NPC_DATA_WIDTH)
    dut.vb_ref_i.value = signed_to_slv(vb_ref, NPC_DATA_WIDTH)
    dut.vc_ref_i.value = signed_to_slv(vc_ref, NPC_DATA_WIDTH)

    # ── Step 3: Enable PWM ──────────────────────────────────────────
    dut.pwm_enb_i.value = 1
    dut._log.info("PWM enabled, waiting for motor model to settle...")

    # ── Step 4: Let the simulation run ──────────────────────────────
    # Gate driver starts within ~1 carrier period (~5000 clk)
    # TIM solver triggers every TIMER_STEPS = CLK_FREQ * Ts = 10 clocks
    # Wait ~3ms (300,000 clk) for measurable current buildup
    #
    # First, wait for gate drivers to start, then do intermediate checks
    await ClockCycles(dut.clk_i, 50_000)  # 0.5ms — gate drivers active
    pwm_on = int(dut.pwm_on_o.value)
    dut._log.info(f"After 50k clk: pwm_on_o = {pwm_on}")

    # Intermediate read of I_ALPHA to see if solver is accumulating
    resp_mid = await sm.read_register(RegAddr.I_ALPHA)
    dut._log.info(f"After ~50k clk: I_ALPHA = {resp_mid.signed_value} (0x{resp_mid.value:012X})")

    await ClockCycles(dut.clk_i, 250_000)  # ~2.5ms more

    resp_mid2 = await sm.read_register(RegAddr.I_ALPHA)
    dut._log.info(f"After ~300k clk: I_ALPHA = {resp_mid2.signed_value} (0x{resp_mid2.value:012X})")

    await ClockCycles(dut.clk_i, 200_000)  # ~2ms more

    # ── Step 5: Read all motor state registers ──────────────────────
    resp = await sm.read_all()

    dut._log.info("═" * 60)
    dut._log.info("Motor State Readback via UART:")
    dut._log.info("═" * 60)
    for addr in range(RegAddr.NUM_REGS):
        name = RegAddr.NAMES.get(addr, f"REG_{addr}")
        val = resp.registers.get(addr, 0)
        sval = resp.signed_value(addr, DATA_WIDTH)
        real_val = fp_to_real(val, DATA_WIDTH)
        dut._log.info(f"  {name:15s} = {sval:>12d}  (0x{val:012X})  [{real_val:+.6f}]")
    dut._log.info("═" * 60)

    # ── Assertions ──────────────────────────────────────────────────
    mask = (1 << DATA_WIDTH) - 1

    # VDC_BUS should match what we wrote
    assert (resp.registers[RegAddr.VDC_BUS] & mask) == (vdc_bus_fp & mask), \
        "VDC_BUS readback mismatch after full chain test"

    # Convert motor outputs to physical units (Q14.28 → real)
    i_alpha_real = fp_to_real(resp.registers[RegAddr.I_ALPHA], DATA_WIDTH)
    i_beta_real  = fp_to_real(resp.registers[RegAddr.I_BETA],  DATA_WIDTH)
    flux_a_real  = fp_to_real(resp.registers[RegAddr.FLUX_ALPHA], DATA_WIDTH)
    flux_b_real  = fp_to_real(resp.registers[RegAddr.FLUX_BETA],  DATA_WIDTH)
    speed_real   = fp_to_real(resp.registers[RegAddr.SPEED_MECH], DATA_WIDTH)
    dut._log.info(
        "Motor state [physical units]: "
        f"ia={i_alpha_real:.4f} A  ib={i_beta_real:.4f} A  "
        f"flux_a={flux_a_real:.4f} Wb  flux_b={flux_b_real:.4f} Wb  "
        f"speed={speed_real:.4f} rad/s"
    )

    # At t≈5 ms with Vdc=300V (Vpeak≈150V), L_total≈0.12 H:
    #   i ≈ V*t/L ≈ 150 × 5e-3 / 0.12 ≈ 6.25 A  (rough upper bound for no-load startup)
    # The simulation only runs ~5 ms so speed is negligible (τ_mech ≈ 0.5 s).
    # Require at least 0.05 A RMS current to confirm the chain is producing output.
    i_rms = math.sqrt(i_alpha_real**2 + i_beta_real**2)
    assert i_rms > 0.05, \
        f"RMS stator current too low ({i_rms:.4f} A) — TIM solver not accumulating with 300V applied"

    # Rotor flux should also be building up (at least 1 mWb)
    flux_mag = math.sqrt(flux_a_real**2 + flux_b_real**2)
    assert flux_mag > 1e-3, \
        f"Rotor flux magnitude too low ({flux_mag:.6f} Wb) — flux equations not responding"

    dut._log.info(
        f"Full chain test PASSED — i_rms={i_rms:.4f} A  flux_mag={flux_mag:.4f} Wb  "
        f"speed={speed_real:.4f} rad/s"
    )


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


# ═══════════════════════════════════════════════════════════════════════
#  TEST 6: L3 diagnostic export — Top_HIL PWM replay vs C model
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_top_hil_pwm_replay_l3(dut):
    """Export a short Top_HIL integrated run and compare it to the C model.

    This is an L3 diagnostic: the C model is fed with voltages decoded from the
    simulated Top_HIL PWM path. That removes carrier phase uncertainty and checks
    the integrated NPC->voltage->TIM path before moving to full-stack C PWM.
    """
    import csv
    import json
    import os
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel

    def env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        return default if raw in (None, "") else int(raw)

    def env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        return default if raw in (None, "") else float(raw)

    def env_path(name: str, default: Path) -> Path:
        raw = os.environ.get(name)
        return default if raw in (None, "") else Path(raw)

    def sig_fp(signal) -> float:
        raw = signal.value
        try:
            signed = raw.to_signed()
        except ValueError as exc:
            raise AssertionError(f"Signal {signal._name} unresolved: {raw.binstr}") from exc
        return signed / float(1 << FP_FRACTION_BITS)

    def rms(values: list[float]) -> float:
        return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0

    clock_hz = env_int("IM_CLOCK_FREQUENCY", 200_000_000)
    pwm_hz = env_int("HIL_PWM_FREQUENCY", 1_000)
    step_cycles = env_int("IM_SOLVER_STEP_CYCLES", 26)
    sample_steps = env_int("HIL_L3_STEPS", 2000)
    warmup_steps = env_int("HIL_L3_WARMUP_STEPS", 100)
    record_interval = env_int("HIL_L3_RECORD_INTERVAL", 1)
    vdc_bus_volts = env_float("HIL_L3_VDC", 1240.0)
    modulation = env_float("HIL_L3_MODULATION", 0.70)
    ref_mode = os.environ.get("HIL_L3_REF_MODE", "fixed")
    ref_freq_hz = env_float("HIL_L3_REF_FREQ_HZ", 60.0)
    vf_base_hz = env_float("HIL_L3_VF_BASE_HZ", 60.0)
    vf_acc_hz_s = env_float("HIL_L3_VF_ACC_HZ_S", 60.0)
    theta0 = env_float("HIL_L3_INITIAL_THETA_RAD", math.pi / 4)
    tload_nm = env_float("HIL_L3_TLOAD_NM", 0.0)

    def env_float_opt(name: str) -> float | None:
        raw = os.environ.get(name)
        return None if raw in (None, "") else float(raw)

    tload_step_nm = env_float_opt("HIL_L3_TLOAD_STEP_NM")
    tload_step_time_s = env_float_opt("HIL_L3_TLOAD_STEP_TIME_S")
    tload_step_applied = False
    out_dir = env_path(
        "HIL_L3_OUT_DIR",
        Path(__file__).resolve().parents[2]
        / "results" / "2026-06-29_campaign_01" / "S0_tacc1s_load000" / "l3_top_pwm_replay_smoke",
    )
    csv_path = out_dir / "top_pwm_replay_vs_c.csv"
    metrics_path = out_dir / "metrics.json"

    clk_period_ps = int(round(1e12 / clock_hz))
    clock = Clock(dut.clk_i, clk_period_ps, unit="ps")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)
    await sm.set_vdc_bus(real_to_fp(vdc_bus_volts))
    await ClockCycles(dut.clk_i, 20)
    await sm.set_torque_load(real_to_fp(tload_nm))
    await ClockCycles(dut.clk_i, 20)

    carrier_max = clock_hz // pwm_hz // 2

    def drive_refs(t_s: float) -> dict[str, float]:
        if ref_mode == "sine":
            f_now = ref_freq_hz
            theta = theta0 + 2.0 * math.pi * ref_freq_hz * t_s
            amp = modulation
            va_ref = int(carrier_max * amp * math.sin(theta))
            vb_ref = int(carrier_max * amp * math.sin(theta - 2.0 * math.pi / 3.0))
            vc_ref = int(carrier_max * amp * math.sin(theta + 2.0 * math.pi / 3.0))
        elif ref_mode == "vf":
            t_acc = vf_base_hz / vf_acc_hz_s if vf_acc_hz_s > 0 else 0.0
            if t_acc > 0 and t_s < t_acc:
                f_now = vf_acc_hz_s * t_s
                theta = theta0 + 2.0 * math.pi * 0.5 * vf_acc_hz_s * t_s * t_s
            else:
                f_now = vf_base_hz
                theta_acc = 2.0 * math.pi * 0.5 * vf_acc_hz_s * t_acc * t_acc if t_acc > 0 else 0.0
                theta = theta0 + theta_acc + 2.0 * math.pi * vf_base_hz * max(0.0, t_s - t_acc)
            amp = modulation * min(max(f_now / vf_base_hz, 0.0), 1.0) if vf_base_hz > 0 else 0.0
            va_ref = int(carrier_max * amp * math.sin(theta))
            vb_ref = int(carrier_max * amp * math.sin(theta - 2.0 * math.pi / 3.0))
            vc_ref = int(carrier_max * amp * math.sin(theta + 2.0 * math.pi / 3.0))
        else:
            f_now = ref_freq_hz
            theta = theta0
            amp = modulation
            ref = int(carrier_max * modulation)
            va_ref = ref
            vb_ref = -(ref // 2)
            vc_ref = -(ref // 2)
        dut.va_ref_i.value = signed_to_slv(va_ref, NPC_DATA_WIDTH)
        dut.vb_ref_i.value = signed_to_slv(vb_ref, NPC_DATA_WIDTH)
        dut.vc_ref_i.value = signed_to_slv(vc_ref, NPC_DATA_WIDTH)
        return {
            "cmd_theta_rad": theta,
            "cmd_freq_hz": f_now,
            "cmd_amp_pu": amp,
            "cmd_va_ref": va_ref,
            "cmd_vb_ref": vb_ref,
            "cmd_vc_ref": vc_ref,
        }

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

    # Wait for NPC gate drivers to become active.
    for _ in range(clock_hz // 200):  # up to 5 ms
        await RisingEdge(dut.clk_i)
        if int(dut.pwm_on_o.value) == 1:
            break
    assert int(dut.pwm_on_o.value) == 1, "Top_HIL PWM did not become active"

    params = IMPhysicalParams.defaults()
    ref_model = InductionMotorReferenceModel(params=params, backend="auto")
    dut._log.info(
        f"L3 Top_HIL PWM replay: steps={sample_steps} warmup={warmup_steps} "
        f"clock={clock_hz}Hz pwm={pwm_hz}Hz step_cycles={step_cycles} "
        f"tload={tload_nm:g}Nm backend={ref_model.backend_name}"
    )

    rows: list[dict] = []
    n_metrics = 0
    se_ia = se_ib = 0.0
    ref2_ia = ref2_ib = 0.0
    sae_fa = sae_fb = sae_wm = 0.0
    progress_every = max(1, sample_steps // 100)
    t_wall_start = time.monotonic()

    for step in range(sample_steps):
        cmd_state = latest_cmd_state
        t_s_now = step * params.ts
        if (
            tload_step_nm is not None
            and tload_step_time_s is not None
            and not tload_step_applied
            and t_s_now >= tload_step_time_s
        ):
            tload_nm = tload_step_nm
            await sm.set_torque_load(real_to_fp(tload_nm))
            tload_step_applied = True
        va = sig_fp(dut.va_motor)
        vb = sig_fp(dut.vb_motor)
        vc = sig_fp(dut.vc_motor)
        c_state = ref_model.step(va, vb, vc, tload_nm)

        await ClockCycles(dut.clk_i, step_cycles)

        vhdl_ia = sig_fp(dut.ialpha_int)
        vhdl_ib = sig_fp(dut.ibeta_int)
        vhdl_fa = sig_fp(dut.flux_rotor_alpha_int)
        vhdl_fb = sig_fp(dut.flux_rotor_beta_int)
        vhdl_wm = sig_fp(dut.speed_mech_int)
        t_s = step * params.ts

        if step >= warmup_steps:
            e_ia = vhdl_ia - c_state.i_alpha
            e_ib = vhdl_ib - c_state.i_beta
            e_fa = vhdl_fa - c_state.flux_alpha
            e_fb = vhdl_fb - c_state.flux_beta
            e_wm = vhdl_wm - c_state.speed_mech
            n_metrics += 1
            se_ia += e_ia * e_ia
            se_ib += e_ib * e_ib
            ref2_ia += c_state.i_alpha * c_state.i_alpha
            ref2_ib += c_state.i_beta * c_state.i_beta
            sae_fa += abs(e_fa)
            sae_fb += abs(e_fb)
            sae_wm += abs(e_wm)
            if ((step - warmup_steps) % record_interval == 0) or step == sample_steps - 1:
                rows.append({
                "step": step,
                "t_s": t_s,
                "va": va,
                "vb": vb,
                "vc": vc,
                "pwm_a": int(dut.pwm_a_o.value),
                "pwm_b": int(dut.pwm_b_o.value),
                "pwm_c": int(dut.pwm_c_o.value),
                "vhdl_i_alpha": vhdl_ia,
                "vhdl_i_beta": vhdl_ib,
                "vhdl_flux_alpha": vhdl_fa,
                "vhdl_flux_beta": vhdl_fb,
                "vhdl_speed": vhdl_wm,
                "ref_i_alpha": c_state.i_alpha,
                "ref_i_beta": c_state.i_beta,
                "ref_flux_alpha": c_state.flux_alpha,
                "ref_flux_beta": c_state.flux_beta,
                "ref_speed": c_state.speed_mech,
                **cmd_state,
                })

        if step % progress_every == 0 and step > 0:
            elapsed = time.monotonic() - t_wall_start
            rate = step / elapsed if elapsed > 0 else 0.0
            eta_s = (sample_steps - step) / rate if rate > 0 else float("inf")
            print(
                f"[L3 {100.0 * step / sample_steps:5.1f}%] "
                f"t={step * params.ts:7.4f}s rows={len(rows):7d} "
                f"elapsed={elapsed/60:6.1f}min ETA={eta_s/60:6.1f}min",
                flush=True,
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    metrics = {
        "level": "L3",
        "test": "top_hil_pwm_replay",
        "status": "diagnostic_smoke",
        "method_note": "C reference is fed with va/vb/vc sampled from Top_HIL internal PWM voltage path at the solver-step boundary approximation.",
        "clock_frequency_hz": clock_hz,
        "pwm_frequency_hz": pwm_hz,
        "solver_step_cycles": step_cycles,
        "sample_steps": sample_steps,
        "warmup_steps": warmup_steps,
        "record_interval": record_interval,
        "csv_rows": len(rows),
        "metrics_samples": n_metrics,
        "duration_s": sample_steps * params.ts,
        "vdc_v": vdc_bus_volts,
        "modulation": modulation,
        "ref_mode": ref_mode,
        "ref_freq_hz": ref_freq_hz,
        "vf_base_hz": vf_base_hz,
        "vf_acc_hz_s": vf_acc_hz_s,
        "initial_theta_rad": theta0,
        "tload_nm": tload_nm,
        "motor": {
            "rs": params.rs, "rr": params.rr, "ls": params.ls, "lr": params.lr,
            "lm": params.lm, "j": params.j, "npp": params.npp, "ts": params.ts,
        },
        "metrics": {
            "nrmse_i_alpha": math.sqrt(se_ia / max(n_metrics, 1)) / max(math.sqrt(ref2_ia / max(n_metrics, 1)), 1e-9),
            "nrmse_i_beta": math.sqrt(se_ib / max(n_metrics, 1)) / max(math.sqrt(ref2_ib / max(n_metrics, 1)), 1e-9),
            "mae_flux_alpha_wb": sae_fa / max(n_metrics, 1),
            "mae_flux_beta_wb": sae_fb / max(n_metrics, 1),
            "mae_speed_rad_s": sae_wm / max(n_metrics, 1),
        },
        "artifacts": {
            "csv": str(csv_path),
            "metrics": str(metrics_path),
        },
    }
    if tload_step_time_s is not None:
        t_arr = [r["t_s"] for r in rows]
        metrics["transient"] = {
            "vhdl": compute_transient_metrics(
                t_arr, [r["vhdl_speed"] for r in rows],
                [r["vhdl_i_alpha"] for r in rows], [r["vhdl_i_beta"] for r in rows],
                tload_step_time_s,
            ),
            "c": compute_transient_metrics(
                t_arr, [r["ref_speed"] for r in rows],
                [r["ref_i_alpha"] for r in rows], [r["ref_i_beta"] for r in rows],
                tload_step_time_s,
            ),
        }
    metrics_path.write_text(json.dumps(metrics, indent=2))
    dut._log.info(f"L3 CSV saved: {csv_path} ({len(rows)} rows)")
    dut._log.info(f"L3 metrics saved: {metrics_path}")
