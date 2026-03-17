"""V/F (Volt/Hertz) stimulus test for TIM_Solver.

Drives the VHDL with a realistic open-loop V/F ramp and compares against
the C reference model.  Results are saved to a CSV for report generation.
"""

import csv
import math
from pathlib import Path

INITIAL_THETA = math.pi / 4  # 45° offset — ensures both α and β channels are excited

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.vf_control import VFControl


DATA_WIDTH = 42
FP_FRACTION_BITS = 28
FP_SCALE = 1 << FP_FRACTION_BITS

# Simulation parameters
SIM_STEPS = 3000       # steps of Ts each (300µs total motor time)
WARMUP_STEPS = 50      # steps to discard before recording

# V/F control parameters (matching PSIM setup)
F_NOMINAL_HZ = 60.0
V_PEAK_NOMINAL = 620.0   # Phase peak voltage at f_nominal [V]  (760 Vrms L-L / sqrt(3) * sqrt(2))
ACC_RAMP_HZ_S = 5000.0   # Fast ramp so we see non-trivial excitation in 100µs
TLOAD_NM = 0.0

# Output CSV path
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
CSV_PATH = REPORTS_DIR / "vf_vhdl_vs_ref.csv"


def signed_to_slv(value: int, width: int) -> int:
    if value < 0:
        return value + (1 << width)
    return value


def real_to_fp(value: float) -> int:
    return int(round(value * FP_SCALE))


def signal_fp_to_real(signal) -> float:
    raw = signal.value
    try:
        signed = raw.to_signed()
    except ValueError as exc:
        raise AssertionError(f"Signal {signal._name} is unresolved: {raw.binstr}") from exc
    return signed / float(FP_SCALE)


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


async def reset_dut(dut, cycles: int = 20) -> None:
    dut.reset_n.value = 0
    dut.va_i.value = 0
    dut.vb_i.value = 0
    dut.vc_i.value = 0
    dut.torque_load_i.value = 0
    await ClockCycles(dut.sysclk, cycles)
    dut.reset_n.value = 1
    await ClockCycles(dut.sysclk, 5)


async def wait_data_valid(dut) -> None:
    while True:
        await RisingEdge(dut.sysclk)
        if int(dut.data_valid_o.value) == 1:
            return


@cocotb.test()
async def test_tim_solver_vf_stimulus(dut):
    """Drive TIM_Solver with V/F ramp and compare against C reference model."""

    clock = Clock(dut.sysclk, 2500, unit="ps")  # 400 MHz — matches CLOCK_FREQUENCY generic
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    params = IMPhysicalParams.defaults()
    ref = InductionMotorReferenceModel(params=params, backend="auto")
    dut._log.info(f"Reference backend: {ref.backend_name}")

    vf = VFControl(
        f_nominal=F_NOMINAL_HZ,
        v_peak_nominal=V_PEAK_NOMINAL,
        acc_ramp_hz_s=ACC_RAMP_HZ_S,
        ts=params.ts,
        tload=TLOAD_NM,
        initial_theta=INITIAL_THETA,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    errors_i_alpha: list[float] = []
    errors_i_beta: list[float] = []
    rows: list[dict] = []

    for step in range(SIM_STEPS):
        va, vb, vc = vf.step()
        tload = vf.tload

        # Apply to VHDL
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
        t_us = step * params.ts * 1e6

        if step >= WARMUP_STEPS:
            errors_i_alpha.append(vhdl_i_alpha - ref_state.i_alpha)
            errors_i_beta.append(vhdl_i_beta - ref_state.i_beta)

            rows.append({
                "step": step,
                "t_us": round(t_us, 4),
                "va": round(va, 6),
                "vb": round(vb, 6),
                "vc": round(vc, 6),
                "f_ref_hz": round(vf.f_ref, 4),
                # VHDL
                "vhdl_i_alpha": vhdl_i_alpha,
                "vhdl_i_beta": vhdl_i_beta,
                "vhdl_flux_alpha": vhdl_flux_alpha,
                "vhdl_flux_beta": vhdl_flux_beta,
                "vhdl_speed": vhdl_speed,
                # Reference
                "ref_i_alpha": ref_state.i_alpha,
                "ref_i_beta": ref_state.i_beta,
                "ref_flux_alpha": ref_state.flux_alpha,
                "ref_flux_beta": ref_state.flux_beta,
                "ref_speed": ref_state.speed_mech,
            })

    # Write CSV
    if rows:
        with CSV_PATH.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        dut._log.info(f"CSV saved: {CSV_PATH} ({len(rows)} rows)")

    # Metrics
    nrmse_i_alpha = rms(errors_i_alpha) / max(rms([r["ref_i_alpha"] for r in rows]), 1e-9)
    nrmse_i_beta = rms(errors_i_beta) / max(rms([r["ref_i_beta"] for r in rows]), 1e-9)

    mae_flux_alpha = sum(abs(r["vhdl_flux_alpha"] - r["ref_flux_alpha"]) for r in rows) / len(rows)
    mae_flux_beta  = sum(abs(r["vhdl_flux_beta"]  - r["ref_flux_beta"])  for r in rows) / len(rows)
    mae_speed      = sum(abs(r["vhdl_speed"]       - r["ref_speed"])       for r in rows) / len(rows)

    dut._log.info("VHDL vs C Reference — 300µs window")
    dut._log.info(f"  NRMSE i_alpha = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta  = {nrmse_i_beta:.6f}")
    dut._log.info(f"  MAE flux_alpha = {mae_flux_alpha:.2e} Wb")
    dut._log.info(f"  MAE flux_beta  = {mae_flux_beta:.2e} Wb")
    dut._log.info(f"  MAE speed_mech = {mae_speed:.6f} rad/s")

    assert nrmse_i_alpha < 0.10, f"i_alpha mismatch: {nrmse_i_alpha:.6f}"
    assert nrmse_i_beta < 0.10, f"i_beta mismatch: {nrmse_i_beta:.6f}"
    assert mae_flux_alpha < 1e-3, f"flux_alpha MAE={mae_flux_alpha:.2e}"
    assert mae_flux_beta  < 1e-3, f"flux_beta MAE={mae_flux_beta:.2e}"
    assert mae_speed      < 2.0,  f"speed MAE={mae_speed:.6f} rad/s"
    dut._log.info(f"MAE flux_alpha={mae_flux_alpha:.2e}  flux_beta={mae_flux_beta:.2e}  speed={mae_speed:.6f}")
