"""Unit tests for BilinearSolverUnit (single-row bilinear state-space solver).

Architecture
------------
BilinearSolverUnit computes ONE row of the bilinear state-space increment:

    stateResult_o = sum_{j} A[j]*X[j]*X[Y[j]]  (if Y[j] >= 0, bilinear)
                  + sum_{j} A[j]*X[j]           (if Y[j] < 0,  linear)
                  + sum_{k} B[k]*U[k]

Y encoding: raw integer stored in the fixed_point_data_t word.
  Y[j] < 0 (MSB=1) → FIXED_POINT_ONE (no extra factor)
  Y[j] >= 0        → X[Y[j]] (bilinear cross term)

Note: BilinearSolverHandler uses 2D matrix ports that GHDL VPI cannot expose.
We test BilinearSolverUnit directly with its accessible 1D vector ports.

Tests
-----
T1 — identity_A_no_input
T2 — pure_B_input
T3 — bilinear_term
T4 — busy_flag
T5 — all_states_nonzero
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

N_SS   = 5
N_IN   = 3
BITS   = 42
FRAC   = 28
SCALE  = 1 << FRAC
MAX_WAIT = 60
Y_DISABLED = -1  # raw integer MSB=1 → no bilinear term


def to_fp(v: float) -> int:
    return int(round(v * SCALE))


def fp_to_real(raw: int) -> float:
    raw &= (1 << BITS) - 1
    if raw & (1 << (BITS - 1)):
        raw -= 1 << BITS
    return raw / SCALE


def slv(v: int) -> int:
    return v & ((1 << BITS) - 1)


def read_fp(sig) -> float:
    return fp_to_real(int(sig.value))


_AVEC = [f"avec_{j}" for j in range(N_SS)]
_XVEC = [f"xvec_{j}" for j in range(N_SS)]
_YVEC = [f"yvec_{j}" for j in range(N_SS)]
_BVEC = [f"bvec_{k}" for k in range(N_IN)]
_UVEC = [f"uvec_{k}" for k in range(N_IN)]


def _set_vec(dut, names, values):
    for name, val in zip(names, values):
        getattr(dut, name).value = val


async def reset_dut(dut, cycles: int = 10) -> None:
    dut.start_i.value = 0
    _set_vec(dut, _AVEC, [0] * N_SS)
    _set_vec(dut, _XVEC, [0] * N_SS)
    _set_vec(dut, _YVEC, [slv(Y_DISABLED)] * N_SS)
    _set_vec(dut, _BVEC, [0] * N_IN)
    _set_vec(dut, _UVEC, [0] * N_IN)
    await ClockCycles(dut.sysclk, cycles)


def golden_result(A, Y_raw, X, B, U) -> float:
    acc = 0.0
    for j in range(N_SS):
        if Y_raw[j] >= 0:
            acc += A[j] * X[j] * X[Y_raw[j]]
        else:
            acc += A[j] * X[j]
    for k in range(N_IN):
        acc += B[k] * U[k]
    return acc


async def run_unit(dut, A, Y_raw, X, B, U) -> float:
    _set_vec(dut, _AVEC, [slv(to_fp(A[j])) for j in range(N_SS)])
    _set_vec(dut, _XVEC, [slv(to_fp(X[j])) for j in range(N_SS)])
    _set_vec(dut, _YVEC, [slv(Y_raw[j]) for j in range(N_SS)])  # raw integer index
    _set_vec(dut, _BVEC, [slv(to_fp(B[k])) for k in range(N_IN)])
    _set_vec(dut, _UVEC, [slv(to_fp(U[k])) for k in range(N_IN)])

    await RisingEdge(dut.sysclk)
    dut.start_i.value = 1
    await RisingEdge(dut.sysclk)
    dut.start_i.value = 0

    for _ in range(MAX_WAIT):
        await RisingEdge(dut.sysclk)
        if int(dut.busy_o.value) == 0:
            break
    else:
        raise AssertionError("Solver never completed (busy stayed high)")

    return read_fp(dut.stateresult_o)


@cocotb.test()
async def test_identity_A_no_input(dut):
    """Avec=[Ts,0,...], Xvec=[1,...], Yvec=[-1,...], B=0 → result=Ts."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    Ts = 100e-9
    A = [0.0] * N_SS;  A[0] = Ts
    Y_raw = [Y_DISABLED] * N_SS
    X = [0.0] * N_SS;  X[0] = 1.0
    B = [0.0] * N_IN
    U = [0.0] * N_IN

    result = await run_unit(dut, A, Y_raw, X, B, U)
    ref = golden_result(A, Y_raw, X, B, U)
    tol = 2 / SCALE
    assert abs(result - ref) <= tol, f"result={result:.6e}  ref={ref:.6e}  err={abs(result-ref):.2e}"
    dut._log.info(f"identity A: result={result:.2e} (ref {ref:.2e}) PASS")


@cocotb.test()
async def test_pure_B_input(dut):
    """Avec=0, Bvec[0]=Ts, Uvec[0]=1.0 → result=Ts."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    Ts = 100e-9
    A = [0.0] * N_SS
    Y_raw = [Y_DISABLED] * N_SS
    X = [0.0] * N_SS
    B = [0.0] * N_IN;  B[0] = Ts
    U = [0.0] * N_IN;  U[0] = 1.0

    result = await run_unit(dut, A, Y_raw, X, B, U)
    ref = golden_result(A, Y_raw, X, B, U)
    tol = 2 / SCALE
    assert abs(result - ref) <= tol, f"result={result:.2e}  ref={ref:.2e}  err={abs(result-ref):.2e}"
    dut._log.info(f"pure B: result={result:.2e} (ref {ref:.2e}) PASS")


@cocotb.test()
async def test_bilinear_term(dut):
    """Yvec[0]=1 (raw index) → result = A[0]*X[0]*X[1] = Ts*2*3."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    Ts = 100e-9
    A = [0.0] * N_SS;  A[0] = Ts
    Y_raw = [Y_DISABLED] * N_SS;  Y_raw[0] = 1  # raw integer 1 → X[1]
    X = [0.0] * N_SS;  X[0] = 2.0;  X[1] = 3.0
    B = [0.0] * N_IN
    U = [0.0] * N_IN

    result = await run_unit(dut, A, Y_raw, X, B, U)
    ref = golden_result(A, Y_raw, X, B, U)
    tol = 4 / SCALE
    assert abs(result - ref) <= tol, f"bilinear: result={result:.6e}  ref={ref:.6e}  err={abs(result-ref):.2e}"
    dut._log.info(f"Bilinear: result={result:.6e}  ref={ref:.6e} PASS")


@cocotb.test()
async def test_busy_flag(dut):
    """busy_o must go 0→1→0 during computation."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    _set_vec(dut, _AVEC, [0] * N_SS)
    _set_vec(dut, _XVEC, [0] * N_SS)
    _set_vec(dut, _YVEC, [slv(Y_DISABLED)] * N_SS)
    _set_vec(dut, _BVEC, [0] * N_IN)
    _set_vec(dut, _UVEC, [0] * N_IN)

    assert int(dut.busy_o.value) == 0, "busy should be 0 before start"

    dut.start_i.value = 1
    await RisingEdge(dut.sysclk)
    dut.start_i.value = 0
    await RisingEdge(dut.sysclk)

    busy_seen = int(dut.busy_o.value) == 1
    for _ in range(MAX_WAIT):
        await RisingEdge(dut.sysclk)
        if int(dut.busy_o.value) == 1:
            busy_seen = True
        else:
            if busy_seen:
                break

    assert busy_seen, "busy_o never went high"
    assert int(dut.busy_o.value) == 0, "busy_o did not return to 0"
    dut._log.info("busy_o: 0 → 1 → 0 ✓")


@cocotb.test()
async def test_all_states_nonzero(dut):
    """Diagonal A with distinct scales, all X nonzero — full accumulation."""
    clock = Clock(dut.sysclk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    Ts = 100e-9
    scales = [1.0, -0.5, 0.25, -0.125, 0.0625]
    A = [Ts * scales[j] for j in range(N_SS)]
    Y_raw = [Y_DISABLED] * N_SS
    X = [1.0, 2.0, 3.0, 4.0, 5.0]
    B = [0.0] * N_IN
    U = [0.0] * N_IN

    result = await run_unit(dut, A, Y_raw, X, B, U)
    ref = golden_result(A, Y_raw, X, B, U)
    tol = 8 / SCALE   # N_SS=5 accumulated multiplications → up to ~5 ULPs
    assert abs(result - ref) <= tol, (
        f"result={result:.6e}  ref={ref:.6e}  err={abs(result-ref):.2e}  tol={tol:.2e}"
    )
    dut._log.info(f"All states: result={result:.2e} (ref {ref:.2e}) PASS")
