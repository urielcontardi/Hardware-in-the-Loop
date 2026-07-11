"""
cocotb Testbench for HIL_AXI_Top — the real synthesized/deployed top-level.

This top was never simulated before: docs/superpowers/plans/2026-07-04-vf-pwm-irq-sync.md
Task 2 only ran a Vivado check_syntax (elaboration-only) on it, never a
functional simulation. Only the simulation-only Top_HIL got a cocotb test
(test_top_hil.py, test_top_hil_carrier_dual_edge).

Goal: reproduce, in simulation, the hardware symptom seen on the EBAZ4205
board where carrier_tick_o (which drives IRQ_F2P) pulses once right after
pwm_ctrl_i.enable is asserted and then never pulses again, instead of
pulsing continuously every carrier period.

Run with:
    cd verification/cocotb
    uv run python run.py --sim nvc --top hil_axi_top
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, First, Timer

CLK_FREQ  = 100_000_000   # matches HIL_AXI_Top generic CLK_FREQ default
PWM_FREQ  = 1_000         # matches HIL_AXI_Top generic PWM_FREQ default
NPC_DW    = 32
TIM_DW    = 42

CLK_PERIOD_NS = int(1e9 / CLK_FREQ)
CARRIER_PERIOD_CYCLES = CLK_FREQ // PWM_FREQ  # 100_000 cycles/period @ 100MHz/1kHz

PWM_CTRL_ENABLE = 0x1


async def reset_dut(dut, cycles: int = 50):
    """Assert active-low resets and hold all inputs at safe/idle defaults."""
    dut.rst_n.value = 0
    dut.solver_rst_n.value = 0
    dut.va_ref_i.value = 0
    dut.vb_ref_i.value = 0
    dut.vc_ref_i.value = 0
    dut.pwm_ctrl_i.value = 0
    dut.vdc_word_i.value = 0
    dut.torque_word_i.value = 0
    dut.coeff_we_i.value = 0
    dut.coeff_apply_i.value = 0
    dut.coeff_addr_i.value = 0
    dut.coeff_data_i.value = 0
    dut.pwm_cap_start_i.value = 0
    dut.pwm_cap_stop_i.value = 0
    dut.pwm_cap_clear_i.value = 0
    dut.pwm_cap_pop_i.value = 0
    dut.pwm_cap_window_i.value = 0
    dut.m_axis_tready.value = 1
    await ClockCycles(dut.clk, cycles)
    dut.rst_n.value = 1
    dut.solver_rst_n.value = 1
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def test_hil_axi_top_carrier_ticks_continuously(dut):
    """Reproduces the hardware symptom: after asserting pwm_ctrl_i.enable=1
    (exactly what vf_tick()'s gpio_set_pwm_ctrl(1,0,0,decim) does on the PS
    side), carrier_tick_o (-> IRQ_F2P on real hardware) should pulse every
    carrier period, not just once. On the EBAZ4205 board, carrier_tick_ctr
    (the independent valley-only diagnostic counter) jumped once then froze,
    and /proc/interrupts for vf_irq stayed stuck at 1 forever."""
    clock = Clock(dut.clk, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    tick_count = 0

    async def counter():
        nonlocal tick_count
        while True:
            await RisingEdge(dut.carrier_tick_o)
            tick_count += 1

    cocotb.start_soon(counter())

    # Give it a few idle periods with enable=0 first (mirrors real boot: the
    # daemon's "queimada de partida" vf_tick() runs once with enable=0 before
    # any "run" command arrives).
    await ClockCycles(dut.clk, CARRIER_PERIOD_CYCLES * 2)
    idle_count = tick_count
    dut._log.info(f"carrier_tick_o pulses with enable=0: {idle_count}")

    # Now assert enable=1 -- exactly what vf_tick() writes to pwm_ctrl_i via
    # gpio_set_pwm_ctrl(1, 0, 0, decim) once run/apply_run() calls it.
    dut.pwm_ctrl_i.value = PWM_CTRL_ENABLE
    n_periods = 8
    await ClockCycles(dut.clk, CARRIER_PERIOD_CYCLES * n_periods)

    enabled_count = tick_count - idle_count
    dut._log.info(
        f"carrier_tick_o pulses with enable=1 over {n_periods} carrier "
        f"periods: {enabled_count} (expected >= {n_periods} if the carrier "
        f"free-runs continuously; LOAD_BOTH_EDGES would give 2x that)"
    )

    assert enabled_count >= n_periods, (
        f"carrier_tick_o only pulsed {enabled_count} times over "
        f"{n_periods} carrier periods after enable=1 -- expected continuous "
        f"periodic ticking, not a one-shot burst. This reproduces the "
        f"EBAZ4205 hardware symptom (carrier_tick_ctr jumps once then "
        f"freezes; /proc/interrupts for vf_irq stuck at 1)."
    )
