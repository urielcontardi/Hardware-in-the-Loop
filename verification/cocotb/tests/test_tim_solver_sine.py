"""Pure-sine stimulus test for TIM_Solver.

Drives BOTH the VHDL DUT and the C reference model with an ideal 60 Hz
sinusoidal voltage (full amplitude, no PWM, no V/F ramp) and compares their
outputs step by step.

Why pure sine?
  - At 60 Hz, 620 V peak, the motor currents rise to ~1 A in 300 µs —
    easily measurable and clearly non-trivial.
  - Removes V/F ramp transient from the comparison window.
  - Validates that the VHDL bilinear solver tracks the C reference model
    under realistic sinusoidal excitation.

Note on visibility:
  At 60 Hz the phase angle advances only 6.5° in 300 µs, so the VOLTAGE
  subplot appears nearly constant.  To see the full sinusoidal waveform run
  the C model for a longer duration via:
      uv run python scripts/vf_report.py --sine --duration 0.2

Output CSV: reports/sine_vhdl_vs_ref.csv
"""

import csv
import math
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.sine_control import SineControl


DATA_WIDTH       = 42
FP_FRACTION_BITS = 28
FP_SCALE         = 1 << FP_FRACTION_BITS

# Simulation parameters
SIM_STEPS    = 3000   # × Ts = 300 µs total motor time
WARMUP_STEPS = 50     # discard initial reset artefacts

# Sine parameters — full-amplitude 60 Hz from t = 0
FREQUENCY_HZ   = 60.0
V_PEAK         = 620.0          # Phase peak [V]
INITIAL_THETA  = math.pi / 4   # 45° → excites both α and β channels from step 0
TLOAD_NM       = 0.0

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
CSV_PATH    = REPORTS_DIR / "sine_vhdl_vs_ref.csv"


# ---------------------------------------------------------------------------
# Fixed-point helpers
# ---------------------------------------------------------------------------
def signed_to_slv(value: int, width: int) -> int:
    return value + (1 << width) if value < 0 else value


def real_to_fp(value: float) -> int:
    return int(round(value * FP_SCALE))


def signal_fp_to_real(signal) -> float:
    raw = signal.value
    try:
        signed = raw.to_signed()
    except ValueError as exc:
        raise AssertionError(
            f"Signal {signal._name} is unresolved: {raw.binstr}"
        ) from exc
    return signed / float(FP_SCALE)


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


# ---------------------------------------------------------------------------
# DUT helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_tim_solver_sine_stimulus(dut):
    """Drive TIM_Solver with 60 Hz pure sine and compare against C reference model."""

    clock = Clock(dut.sysclk, 2500, unit="ps")  # 400 MHz — matches CLOCK_FREQUENCY generic
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    params = IMPhysicalParams.defaults()
    ref    = InductionMotorReferenceModel(params=params, backend="auto")
    dut._log.info(f"Reference backend: {ref.backend_name}")

    sine = SineControl(
        frequency_hz  = FREQUENCY_HZ,
        v_peak        = V_PEAK,
        ts            = params.ts,
        initial_theta = INITIAL_THETA,
        tload         = TLOAD_NM,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    errors_i_alpha: list[float] = []
    errors_i_beta:  list[float] = []
    rows: list[dict] = []

    for step in range(SIM_STEPS):
        va, vb, vc = sine.step()
        tload = sine.tload

        # Apply voltages to VHDL DUT
        dut.va_i.value        = signed_to_slv(real_to_fp(va),    DATA_WIDTH)
        dut.vb_i.value        = signed_to_slv(real_to_fp(vb),    DATA_WIDTH)
        dut.vc_i.value        = signed_to_slv(real_to_fp(vc),    DATA_WIDTH)
        dut.torque_load_i.value = signed_to_slv(real_to_fp(tload), DATA_WIDTH)

        await wait_data_valid(dut)

        vhdl_i_alpha    = signal_fp_to_real(dut.ialpha_o)
        vhdl_i_beta     = signal_fp_to_real(dut.ibeta_o)
        vhdl_flux_alpha = signal_fp_to_real(dut.flux_rotor_alpha_o)
        vhdl_flux_beta  = signal_fp_to_real(dut.flux_rotor_beta_o)
        vhdl_speed      = signal_fp_to_real(dut.speed_mech_o)

        ref_state = ref.step(va, vb, vc, tload)
        t_us = step * params.ts * 1e6

        if step >= WARMUP_STEPS:
            errors_i_alpha.append(vhdl_i_alpha - ref_state.i_alpha)
            errors_i_beta.append(vhdl_i_beta  - ref_state.i_beta)

            rows.append({
                "step":             step,
                "t_us":             round(t_us, 4),
                "va":               round(va, 6),
                "vb":               round(vb, 6),
                "vc":               round(vc, 6),
                "f_ref_hz":         round(sine.f_ref, 4),
                # VHDL DUT
                "vhdl_i_alpha":     vhdl_i_alpha,
                "vhdl_i_beta":      vhdl_i_beta,
                "vhdl_flux_alpha":  vhdl_flux_alpha,
                "vhdl_flux_beta":   vhdl_flux_beta,
                "vhdl_speed":       vhdl_speed,
                # C reference
                "ref_i_alpha":      ref_state.i_alpha,
                "ref_i_beta":       ref_state.i_beta,
                "ref_flux_alpha":   ref_state.flux_alpha,
                "ref_flux_beta":    ref_state.flux_beta,
                "ref_speed":        ref_state.speed_mech,
            })

    # Write CSV
    if rows:
        with CSV_PATH.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        dut._log.info(f"CSV saved: {CSV_PATH} ({len(rows)} rows)")

    # Metrics
    nrmse_i_alpha  = rms(errors_i_alpha) / max(rms([r["ref_i_alpha"] for r in rows]), 1e-9)
    nrmse_i_beta   = rms(errors_i_beta)  / max(rms([r["ref_i_beta"]  for r in rows]), 1e-9)

    mae_flux_alpha = sum(abs(r["vhdl_flux_alpha"] - r["ref_flux_alpha"]) for r in rows) / len(rows)
    mae_flux_beta  = sum(abs(r["vhdl_flux_beta"]  - r["ref_flux_beta"])  for r in rows) / len(rows)
    mae_speed      = sum(abs(r["vhdl_speed"]       - r["ref_speed"])       for r in rows) / len(rows)

    dut._log.info(f"Pure sine {FREQUENCY_HZ} Hz, {V_PEAK} V peak — 300 µs window")
    dut._log.info(f"  NRMSE i_alpha = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta  = {nrmse_i_beta:.6f}")
    dut._log.info(f"  MAE flux_alpha = {mae_flux_alpha:.2e} Wb")
    dut._log.info(f"  MAE flux_beta  = {mae_flux_beta:.2e} Wb")
    dut._log.info(f"  MAE speed_mech = {mae_speed:.6f} rad/s")

    assert nrmse_i_alpha < 0.10, f"i_alpha NRMSE={nrmse_i_alpha:.4f}"
    assert nrmse_i_beta  < 0.10, f"i_beta  NRMSE={nrmse_i_beta:.4f}"
    assert mae_flux_alpha < 1e-3, f"flux_alpha MAE={mae_flux_alpha:.2e}"
    assert mae_flux_beta  < 1e-3, f"flux_beta  MAE={mae_flux_beta:.2e}"
    assert mae_speed      < 2.0,  f"speed MAE={mae_speed:.6f} rad/s"
