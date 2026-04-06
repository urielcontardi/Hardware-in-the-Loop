"""Unit tests for the ClarkeTransform VHDL module.

Tests
-----
T1 — balanced_alpha_axis
    Va=1, Vb=-0.5, Vc=-0.5  →  α=1, β=0, zero=0  (positive-sequence on α axis)

T2 — balanced_beta_axis
    Va=0, Vb=sin(120°), Vc=-sin(120°)  →  α=0, β=1, zero=0  (β-axis only)

T3 — zero_sequence
    Va=Vb=Vc=1  →  α=0, β=0, zero=1

T4 — pipeline_latency
    Assert data_valid_o arrives exactly PIPE_DEPTH cycles after data_valid_i
    (6 in GHDL/cocotb VPI: 5-cycle RTL + 1 VPI-deposit offset).

T5 — sweep_random
    Apply 20 random balanced 3-phase inputs and compare with Python golden.

T6 — large_amplitude
    Near full-scale values — verify no overflow.
"""

import math
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

DATA_WIDTH  = 42
FRAC_WIDTH  = 28
FP_SCALE    = 1 << FRAC_WIDTH
PIPE_DEPTH  = 6   # ClarkeTransform pipeline latency as seen by GHDL/cocotb VPI
                  # VHDL has 5-cycle RTL latency (v1.4 6-stage pipeline); VPI deposit adds 1 effective cycle
TOL_ULP     = 6   # allowed error in LSBs:
                  # COEFF_2_3 = round(2/3 * 2^28) introduces ≤ 0.333 * alphaSum_real ULPs
                  # shift_right(b,1) and shift_right(c,1) add ≤ 1 ULP each
                  # Combined: ≤ 0.333 * max_alphaSum_real + 2 ≤ 6 ULPs for amplitudes ≤ 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def real_to_fp(v: float) -> int:
    return int(round(v * FP_SCALE))


def fp_to_real(raw: int) -> float:
    """Convert a DATA_WIDTH-bit raw integer (signed or unsigned) to float."""
    raw &= (1 << DATA_WIDTH) - 1          # mask to DATA_WIDTH bits (handles cocotb 2.x signed returns)
    if raw & (1 << (DATA_WIDTH - 1)):
        raw -= 1 << DATA_WIDTH
    return raw / FP_SCALE


def to_slv(v: int) -> int:
    """Signed Q14.28 integer — pass directly (cocotb handles signed ports)."""
    return v


def read_signed(sig) -> int:
    return int(sig.value)


def clarke_python(a: float, b: float, c: float):
    """Reference Clarke transform (matches VHDL equations)."""
    alpha = (2.0 / 3.0) * (a - 0.5 * b - 0.5 * c)
    beta  = (1.0 / math.sqrt(3.0)) * (b - c)
    zero  = (1.0 / 3.0) * (a + b + c)
    return alpha, beta, zero


async def reset_dut(dut, cycles: int = 5) -> None:
    dut.reset_n.value    = 0
    dut.data_valid_i.value = 0
    dut.a_in.value = 0
    dut.b_in.value = 0
    dut.c_in.value = 0
    await ClockCycles(dut.sysclk, cycles)
    dut.reset_n.value = 1
    await ClockCycles(dut.sysclk, 2)


async def apply_and_read(dut, a: float, b: float, c: float):
    """Drive inputs for one cycle, then wait for the output (3-cycle pipeline)."""
    dut.a_in.value = to_slv(real_to_fp(a))
    dut.b_in.value = to_slv(real_to_fp(b))
    dut.c_in.value = to_slv(real_to_fp(c))
    dut.data_valid_i.value = 1
    await RisingEdge(dut.sysclk)
    dut.data_valid_i.value = 0

    # Wait for data_valid_o
    for _ in range(PIPE_DEPTH + 2):
        await RisingEdge(dut.sysclk)
        if int(dut.data_valid_o.value) == 1:
            return (
                fp_to_real(read_signed(dut.alpha_o)),
                fp_to_real(read_signed(dut.beta_o)),
                fp_to_real(read_signed(dut.zero_o)),
            )

    raise AssertionError("data_valid_o never asserted")


def assert_close(name: str, got: float, want: float, tol_real: float):
    err = abs(got - want)
    assert err <= tol_real, (
        f"{name}: got={got:.8f}  want={want:.8f}  err={err:.2e}  tol={tol_real:.2e}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_balanced_alpha_axis(dut):
    """Va=1, Vb=-0.5, Vc=-0.5 → α=1, β=0, zero=0."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    a, b, c = 1.0, -0.5, -0.5
    alpha, beta, zero = await apply_and_read(dut, a, b, c)
    ref_alpha, ref_beta, ref_zero = clarke_python(a, b, c)

    tol = TOL_ULP / FP_SCALE
    assert_close("alpha", alpha, ref_alpha, tol)
    assert_close("beta",  beta,  ref_beta,  tol)
    assert_close("zero",  zero,  ref_zero,  tol)
    dut._log.info(f"α={alpha:.6f} (ref {ref_alpha:.6f})  β={beta:.6f}  zero={zero:.6f}")


@cocotb.test()
async def test_balanced_beta_axis(dut):
    """Va=0, Vb=sin120, Vc=-sin120 → α=0, β=1, zero=0."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    s = math.sin(math.radians(120))
    a, b, c = 0.0, s, -s
    alpha, beta, zero = await apply_and_read(dut, a, b, c)
    ref_alpha, ref_beta, ref_zero = clarke_python(a, b, c)

    tol = TOL_ULP / FP_SCALE
    assert_close("alpha", alpha, ref_alpha, tol)
    assert_close("beta",  beta,  ref_beta,  tol)
    assert_close("zero",  zero,  ref_zero,  tol)
    dut._log.info(f"α={alpha:.6f} (ref {ref_alpha:.6f})  β={beta:.6f}")


@cocotb.test()
async def test_zero_sequence(dut):
    """Va=Vb=Vc=1 → α=0, β=0, zero=1."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    alpha, beta, zero = await apply_and_read(dut, 1.0, 1.0, 1.0)
    tol = TOL_ULP / FP_SCALE
    assert_close("alpha", alpha, 0.0, tol)
    assert_close("beta",  beta,  0.0, tol)
    assert_close("zero",  zero,  1.0, tol)
    dut._log.info(f"α={alpha:.6f}  β={beta:.6f}  zero={zero:.6f}")


@cocotb.test()
async def test_pipeline_latency(dut):
    """data_valid_o must assert exactly PIPE_DEPTH cycles after data_valid_i."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.a_in.value = to_slv(real_to_fp(1.0))
    dut.b_in.value = to_slv(real_to_fp(-0.5))
    dut.c_in.value = to_slv(real_to_fp(-0.5))
    dut.data_valid_i.value = 1
    await RisingEdge(dut.sysclk)   # cycle 0: inputs latched
    dut.data_valid_i.value = 0

    for cycle in range(1, PIPE_DEPTH + 3):
        await RisingEdge(dut.sysclk)
        valid = int(dut.data_valid_o.value)
        expected = 1 if cycle == PIPE_DEPTH else 0
        assert valid == expected, (
            f"Cycle {cycle}: data_valid_o={valid}, expected={expected} "
            f"(pipeline depth={PIPE_DEPTH})"
        )
        if valid:
            dut._log.info(f"data_valid_o asserted at cycle {cycle} ✓")
            break


@cocotb.test()
async def test_sweep_random(dut):
    """20 random balanced 3-phase inputs vs Python golden."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    rng = random.Random(42)
    tol = TOL_ULP / FP_SCALE
    errors = []

    for i in range(20):
        # Random amplitude and phase — keep within representable range
        amp   = rng.uniform(0.01, 4.0)
        theta = rng.uniform(0, 2 * math.pi)
        a = amp * math.cos(theta)
        b = amp * math.cos(theta - 2 * math.pi / 3)
        c = amp * math.cos(theta + 2 * math.pi / 3)

        alpha, beta, zero = await apply_and_read(dut, a, b, c)
        ref_alpha, ref_beta, ref_zero = clarke_python(a, b, c)

        err_a = abs(alpha - ref_alpha)
        err_b = abs(beta  - ref_beta)
        errors.append(max(err_a, err_b))

        assert err_a <= tol, f"[{i}] alpha err={err_a:.2e} got={alpha:.6f} want={ref_alpha:.6f}"
        assert err_b <= tol, f"[{i}] beta  err={err_b:.2e} got={beta:.6f} want={ref_beta:.6f}"

    dut._log.info(f"Sweep: max_err={max(errors):.2e}  tol={tol:.2e}  PASS")


@cocotb.test()
async def test_large_amplitude(dut):
    """Near full-scale values — verify no overflow/wraparound."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Q14.28: integer range ±2^13 = ±8192; stay at ~6000 for safety
    a, b, c = 6000.0, -3000.0, -3000.0
    alpha, beta, zero = await apply_and_read(dut, a, b, c)
    ref_alpha, ref_beta, _ = clarke_python(a, b, c)

    # COEFF_2_3 = round(2/3 * 2^28) introduces error ≈ 0.334 * alphaSum_real ULPs
    # alphaSum_real = a - b/2 - c/2 = 6000 + 1500 + 1500 = 9000
    # Plus ≤2 ULPs from shift_right(b,1) and shift_right(c,1)
    alpha_sum = a - 0.5 * b - 0.5 * c
    tol = (0.334 * abs(alpha_sum) + 2) / FP_SCALE
    assert_close("alpha", alpha, ref_alpha, tol)
    assert_close("beta",  beta,  ref_beta,  tol)
    dut._log.info(f"Large: α={alpha:.2f} (ref {ref_alpha:.2f})  β={beta:.2f}")
