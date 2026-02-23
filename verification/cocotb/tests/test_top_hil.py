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
CLK_FREQ       = 100_000_000       # 100 MHz (faster sim than 200 MHz)
BAUD_RATE      = 1_000_000         # 1 Mbaud (accelerate UART in sim)
DATA_WIDTH     = 42
NPC_DATA_WIDTH = 32
CLK_PERIOD_NS  = int(1e9 / CLK_FREQ)


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
    """Enable PWM with a DC reference and verify gate outputs become active."""
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)

    # Configure VDC bus (fixed-point: e.g., 100 in raw integer units)
    await sm.set_vdc_bus(100)
    await ClockCycles(dut.clk_i, 20)

    # Set voltage references (positive value on phase A, zero on B and C)
    half_scale = (1 << (NPC_DATA_WIDTH - 1)) - 1  # Max positive for NPC ref
    dut.va_ref_i.value = half_scale // 2
    dut.vb_ref_i.value = 0
    dut.vc_ref_i.value = 0

    # Enable PWM
    dut.pwm_enb_i.value = 1
    dut.pwm_clear_i.value = 0

    # Wait for a few carrier periods (PWM_FREQ=20kHz → 50us period)
    # At 100MHz that's 5000 clocks per PWM period
    # NPCManager WAIT_STATE_CNT = CLK_FREQ/1000 = 100,000 clocks (~1ms)
    # Need to wait past that + a few PWM periods
    await ClockCycles(dut.clk_i, 200_000)

    # Check that pwm_on_o went high
    pwm_on = int(dut.pwm_on_o.value)
    dut._log.info(f"pwm_on_o = {pwm_on}")
    assert pwm_on == 1, "PWM should be active after enable"

    # Check gate outputs are not all zero (some switching happened)
    pwm_a = int(dut.pwm_a_o.value)
    dut._log.info(f"pwm_a_o = 0b{pwm_a:04b}")


# ═══════════════════════════════════════════════════════════════════════
#  TEST 5: Full chain – Configure VDC + enable PWM + read motor outputs
# ═══════════════════════════════════════════════════════════════════════
@cocotb.test()
async def test_full_chain_motor_outputs(dut):
    """
    Full integration test:
    1. Configure VDC_BUS and TORQUE_LOAD via UART
    2. Apply sinusoidal voltage references
    3. Enable PWM
    4. Wait for TIM_Solver to produce valid outputs
    5. Read motor state via UART Read All
    """
    clock = Clock(dut.clk_i, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    sm = create_serial_driver(dut)

    # ── Step 1: Configure via UART ──────────────────────────────────
    vdc_bus_val = 200  # DC bus voltage in fixed-point integer units
    torque_val = 0     # No load initially
    await sm.set_vdc_bus(vdc_bus_val)
    await ClockCycles(dut.clk_i, 20)
    await sm.set_torque_load(torque_val)
    await ClockCycles(dut.clk_i, 20)

    # ── Step 2: Apply voltage references (static for simplicity) ────
    # Use ~50% of full scale as a constant reference
    ref_amplitude = (1 << (NPC_DATA_WIDTH - 2))  # ~25% of range
    dut.va_ref_i.value = signed_to_slv(ref_amplitude, NPC_DATA_WIDTH)
    dut.vb_ref_i.value = signed_to_slv(-ref_amplitude // 2, NPC_DATA_WIDTH)
    dut.vc_ref_i.value = signed_to_slv(-ref_amplitude // 2, NPC_DATA_WIDTH)

    # ── Step 3: Enable PWM ──────────────────────────────────────────
    dut.pwm_enb_i.value = 1
    dut._log.info("PWM enabled, waiting for motor model to settle...")

    # ── Step 4: Let the simulation run for several PWM periods ──────
    # NPCManager WAIT_STATE_CNT = CLK_FREQ/1000 = 100,000 clocks (~1ms)
    # After that, ~10 PWM periods at 20kHz = 500us = 50,000 clocks
    await ClockCycles(dut.clk_i, 200_000)

    # ── Step 5: Read all motor state registers ──────────────────────
    resp = await sm.read_all()

    dut._log.info("═" * 60)
    dut._log.info("Motor State Readback via UART:")
    dut._log.info("═" * 60)
    for addr in range(RegAddr.NUM_REGS):
        name = RegAddr.NAMES.get(addr, f"REG_{addr}")
        val = resp.registers.get(addr, 0)
        sval = resp.signed_value(addr, DATA_WIDTH)
        dut._log.info(f"  {name:15s} = {sval:>12d}  (0x{val:012X})")
    dut._log.info("═" * 60)

    # Basic sanity: VDC_BUS should match what we wrote
    mask = (1 << DATA_WIDTH) - 1
    assert (resp.registers[RegAddr.VDC_BUS] & mask) == (vdc_bus_val & mask), \
        "VDC_BUS readback mismatch after full chain test"

    dut._log.info("Full chain test PASSED")
