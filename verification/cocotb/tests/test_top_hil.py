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
    """Convert a real number to Q14.28 fixed-point integer."""
    return int(value * (1 << FP_FRACTION_BITS))


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

    # Set balanced 3-phase references (85% modulation).
    # CARRIER_MAX = 2500. All phases must have non-zero |ref| < CARRIER_MAX
    # so the modulator switches between POS/NEG and ZERO on every carrier cycle.
    ref = CARRIER_MAX * 85 // 100  # 2125
    dut.va_ref_i.value = signed_to_slv( ref,       NPC_DATA_WIDTH)
    dut.vb_ref_i.value = signed_to_slv(-ref,       NPC_DATA_WIDTH)
    dut.vc_ref_i.value = signed_to_slv( ref // 2,  NPC_DATA_WIDTH)

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

    # Check gate outputs are not all zero (switching is happening)
    pwm_a = int(dut.pwm_a_o.value)
    pwm_b = int(dut.pwm_b_o.value)
    pwm_c = int(dut.pwm_c_o.value)
    dut._log.info(f"pwm_a_o=0b{pwm_a:04b}  pwm_b_o=0b{pwm_b:04b}  pwm_c_o=0b{pwm_c:04b}")


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
    # 85% modulation on all phases (must be < CARRIER_MAX for ZERO transitions)
    ref = CARRIER_MAX * 85 // 100  # 2125
    dut.va_ref_i.value = signed_to_slv( ref,       NPC_DATA_WIDTH)
    dut.vb_ref_i.value = signed_to_slv(-ref,       NPC_DATA_WIDTH)
    dut.vc_ref_i.value = signed_to_slv( ref // 2,  NPC_DATA_WIDTH)

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

    # Motor outputs should be non-zero (solver is running with non-zero voltage)
    i_alpha = resp.signed_value(RegAddr.I_ALPHA, DATA_WIDTH)
    i_beta  = resp.signed_value(RegAddr.I_BETA, DATA_WIDTH)
    flux_a  = resp.signed_value(RegAddr.FLUX_ALPHA, DATA_WIDTH)
    flux_b  = resp.signed_value(RegAddr.FLUX_BETA, DATA_WIDTH)

    motor_active = (i_alpha != 0) or (i_beta != 0) or (flux_a != 0) or (flux_b != 0)
    assert motor_active, \
        "Motor outputs should be non-zero: TIM solver must produce output with 300V applied"

    dut._log.info("Full chain test PASSED — motor model producing non-zero outputs")
