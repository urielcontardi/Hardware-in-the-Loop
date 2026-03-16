"""Reference-model comparison test for TIM_Solver.

Compares TIM_Solver fixed-point outputs against the induction-motor model from the
submodule in verification/reference_models/induction-motor-model.
"""

import math

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel


DATA_WIDTH = 42
FP_FRACTION_BITS = 28
CLK_FREQ = 100_000_000
CLK_PERIOD_NS = int(1e9 / CLK_FREQ)

SIM_STEPS = 500
WARMUP_STEPS = 100


def signed_to_slv(value: int, width: int) -> int:
    if value < 0:
        return value + (1 << width)
    return value


def real_to_fp(value: float) -> int:
    return int(round(value * (1 << FP_FRACTION_BITS)))


def fp_to_real(raw: int, width: int = DATA_WIDTH) -> float:
    if raw & (1 << (width - 1)):
        raw -= 1 << width
    return raw / float(1 << FP_FRACTION_BITS)


def signal_fp_to_real(signal) -> float:
    raw = signal.value
    try:
        signed = raw.signed_integer
    except ValueError as exc:
        raise AssertionError(f"Signal {signal._name} is unresolved: {raw.binstr}") from exc
    return signed / float(1 << FP_FRACTION_BITS)


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


async def reset_dut(dut, cycles: int = 20):
    dut.reset_n.value = 0
    dut.va_i.value = 0
    dut.vb_i.value = 0
    dut.vc_i.value = 0
    dut.torque_load_i.value = 0
    await ClockCycles(dut.sysclk, cycles)
    dut.reset_n.value = 1
    await ClockCycles(dut.sysclk, 5)


async def wait_data_valid(dut):
    while True:
        await RisingEdge(dut.sysclk)
        if int(dut.data_valid_o.value) == 1:
            return


@cocotb.test()
async def test_tim_solver_matches_reference_model(dut):
    """Run TIM_Solver and compare key states against the reference model."""

    clock = Clock(dut.sysclk, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    params = IMPhysicalParams.defaults()
    ref = InductionMotorReferenceModel(params=params, backend="auto")

    dut._log.info(f"Reference backend selected: {ref.backend_name}")
    if getattr(ref, "fallback_reason", ""):
        dut._log.warning(f"C backend unavailable, using fallback: {ref.fallback_reason}")

    # Piecewise-constant phase voltages with zero-sequence = 0.
    # This gives deterministic excitation and aligns with existing VHDL TB style.
    stimuli = [
        (100.0, 300.0, -400.0, 0.0),
        (-150.0, 250.0, -100.0, 0.0),
    ]

    errors_i_alpha: list[float] = []
    errors_i_beta: list[float] = []
    errors_flux_alpha: list[float] = []
    errors_flux_beta: list[float] = []
    errors_speed: list[float] = []

    refs_i_alpha: list[float] = []
    refs_i_beta: list[float] = []
    refs_flux_alpha: list[float] = []
    refs_flux_beta: list[float] = []
    vhdl_i_alpha_samples: list[float] = []
    vhdl_i_beta_samples: list[float] = []
    vhdl_flux_alpha_samples: list[float] = []
    vhdl_flux_beta_samples: list[float] = []

    va, vb, vc, tload = stimuli[0]
    dut.va_i.value = signed_to_slv(real_to_fp(va), DATA_WIDTH)
    dut.vb_i.value = signed_to_slv(real_to_fp(vb), DATA_WIDTH)
    dut.vc_i.value = signed_to_slv(real_to_fp(vc), DATA_WIDTH)
    dut.torque_load_i.value = signed_to_slv(real_to_fp(tload), DATA_WIDTH)

    for step in range(SIM_STEPS):
        if step == SIM_STEPS // 2:
            va, vb, vc, tload = stimuli[1]
            dut.va_i.value = signed_to_slv(real_to_fp(va), DATA_WIDTH)
            dut.vb_i.value = signed_to_slv(real_to_fp(vb), DATA_WIDTH)
            dut.vc_i.value = signed_to_slv(real_to_fp(vc), DATA_WIDTH)
            dut.torque_load_i.value = signed_to_slv(real_to_fp(tload), DATA_WIDTH)

        await wait_data_valid(dut)

        vhdl_i_alpha = signal_fp_to_real(dut.ialpha_o)
        vhdl_i_beta = signal_fp_to_real(dut.ibeta_o)
        vhdl_flux_alpha = signal_fp_to_real(dut.flux_rotor_alpha_o)
        vhdl_flux_beta = signal_fp_to_real(dut.flux_rotor_beta_o)
        vhdl_speed = signal_fp_to_real(dut.speed_mech_o)

        ref_state = ref.step(va, vb, vc, tload)

        if step >= WARMUP_STEPS:
            vhdl_i_alpha_samples.append(vhdl_i_alpha)
            vhdl_i_beta_samples.append(vhdl_i_beta)
            vhdl_flux_alpha_samples.append(vhdl_flux_alpha)
            vhdl_flux_beta_samples.append(vhdl_flux_beta)

            refs_i_alpha.append(ref_state.i_alpha)
            refs_i_beta.append(ref_state.i_beta)
            refs_flux_alpha.append(ref_state.flux_alpha)
            refs_flux_beta.append(ref_state.flux_beta)

            errors_i_alpha.append(vhdl_i_alpha - ref_state.i_alpha)
            errors_i_beta.append(vhdl_i_beta - ref_state.i_beta)
            errors_flux_alpha.append(vhdl_flux_alpha - ref_state.flux_alpha)
            errors_flux_beta.append(vhdl_flux_beta - ref_state.flux_beta)
            errors_speed.append(vhdl_speed - ref_state.speed_mech)

            if step in (WARMUP_STEPS, WARMUP_STEPS + 1, WARMUP_STEPS + 10):
                dut._log.info(
                    "sample step=%d | vhdl(ia,ib,fa,fb)=(%.6f, %.6f, %.6f, %.6f) "
                    "ref=(%.6f, %.6f, %.6f, %.6f)",
                    step,
                    vhdl_i_alpha,
                    vhdl_i_beta,
                    vhdl_flux_alpha,
                    vhdl_flux_beta,
                    ref_state.i_alpha,
                    ref_state.i_beta,
                    ref_state.flux_alpha,
                    ref_state.flux_beta,
                )
                dut._log.info(
                    "internals step=%d | timer_tick=%s clarke_valid=%s solver_busy=%s valpha=%s vbeta=%s",
                    step,
                    dut.timer_tick.value,
                    dut.clarke_valid.value,
                    dut.solver_busy.value,
                    dut.valpha.value,
                    dut.vbeta.value,
                )

    assert errors_i_alpha, "No comparison samples were collected"

    nrmse_i_alpha = rms(errors_i_alpha) / max(rms(refs_i_alpha), 1e-9)
    nrmse_i_beta = rms(errors_i_beta) / max(rms(refs_i_beta), 1e-9)
    nrmse_flux_alpha = rms(errors_flux_alpha) / max(rms(refs_flux_alpha), 1e-9)
    nrmse_flux_beta = rms(errors_flux_beta) / max(rms(refs_flux_beta), 1e-9)
    mae_speed = sum(abs(v) for v in errors_speed) / len(errors_speed)

    dut._log.info("Reference comparison metrics:")
    dut._log.info(f"  RMS vhdl i_alpha = {rms(vhdl_i_alpha_samples):.6f}")
    dut._log.info(f"  RMS ref  i_alpha = {rms(refs_i_alpha):.6f}")
    dut._log.info(f"  RMS vhdl i_beta  = {rms(vhdl_i_beta_samples):.6f}")
    dut._log.info(f"  RMS ref  i_beta  = {rms(refs_i_beta):.6f}")
    dut._log.info(f"  NRMSE i_alpha     = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta      = {nrmse_i_beta:.6f}")
    dut._log.info(f"  NRMSE flux_alpha  = {nrmse_flux_alpha:.6f}")
    dut._log.info(f"  NRMSE flux_beta   = {nrmse_flux_beta:.6f}")
    dut._log.info(f"  MAE speed_mech    = {mae_speed:.6f} rad/s")

    # Conservative thresholds to account for fixed-point arithmetic differences.
    assert nrmse_i_alpha < 0.30, f"i_alpha mismatch too high: {nrmse_i_alpha:.6f}"
    assert nrmse_i_beta < 0.30, f"i_beta mismatch too high: {nrmse_i_beta:.6f}"
    assert nrmse_flux_alpha < 0.35, f"flux_alpha mismatch too high: {nrmse_flux_alpha:.6f}"
    assert nrmse_flux_beta < 0.35, f"flux_beta mismatch too high: {nrmse_flux_beta:.6f}"
    assert mae_speed < 2.0, f"speed mismatch too high: {mae_speed:.6f} rad/s"
