"""Reference-model comparison test for TIM_Solver.

Compares TIM_Solver fixed-point outputs against the induction-motor model from the
submodule in verification/reference_models/induction-motor-model.

Generates at the end:
  reports/ref_vhdl_vs_ref.csv   — step-by-step VHDL vs C data
  reports/ref_report.html       — interactive comparison report
"""

import csv
import math
import subprocess
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel


DATA_WIDTH       = 42
FP_FRACTION_BITS = 28
CLK_PERIOD_NS    = 10   # 100 MHz test clock (CLOCK_FREQUENCY generic = 400 MHz via run.py)

SIM_STEPS    = 500
WARMUP_STEPS = 100

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
CSV_PATH    = REPORTS_DIR / "ref_vhdl_vs_ref.csv"
HTML_PATH   = REPORTS_DIR / "ref_report.html"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


# ---------------------------------------------------------------------------
# Fixed-point helpers
# ---------------------------------------------------------------------------
def signed_to_slv(value: int, width: int) -> int:
    return value + (1 << width) if value < 0 else value


def real_to_fp(value: float) -> int:
    return int(round(value * (1 << FP_FRACTION_BITS)))


def signal_fp_to_real(signal) -> float:
    raw = signal.value
    try:
        signed = raw.to_signed()
    except ValueError as exc:
        raise AssertionError(f"Signal {signal._name} is unresolved: {raw.binstr}") from exc
    return signed / float(1 << FP_FRACTION_BITS)


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


# ---------------------------------------------------------------------------
# DUT helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_tim_solver_matches_reference_model(dut):
    """Run TIM_Solver and compare key states against the reference model."""

    clock = Clock(dut.sysclk, CLK_PERIOD_NS, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    params = IMPhysicalParams.defaults()
    ref    = InductionMotorReferenceModel(params=params, backend="auto")

    dut._log.info(f"Reference backend selected: {ref.backend_name}")

    # Piecewise-constant phase voltages — gives deterministic, DC-like excitation
    stimuli = [
        (100.0,  300.0, -400.0, 0.0),   # steps 0..249
        (-150.0, 250.0, -100.0, 0.0),   # steps 250..499
    ]

    rows: list[dict] = []
    errors_i_alpha:    list[float] = []
    errors_i_beta:     list[float] = []
    errors_flux_alpha: list[float] = []
    errors_flux_beta:  list[float] = []
    errors_speed:      list[float] = []
    refs_i_alpha:      list[float] = []
    refs_i_beta:       list[float] = []

    va, vb, vc, tload = stimuli[0]
    dut.va_i.value        = signed_to_slv(real_to_fp(va),    DATA_WIDTH)
    dut.vb_i.value        = signed_to_slv(real_to_fp(vb),    DATA_WIDTH)
    dut.vc_i.value        = signed_to_slv(real_to_fp(vc),    DATA_WIDTH)
    dut.torque_load_i.value = signed_to_slv(real_to_fp(tload), DATA_WIDTH)

    for step in range(SIM_STEPS):
        if step == SIM_STEPS // 2:
            va, vb, vc, tload = stimuli[1]
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
            errors_i_alpha.append(vhdl_i_alpha    - ref_state.i_alpha)
            errors_i_beta.append(vhdl_i_beta      - ref_state.i_beta)
            errors_flux_alpha.append(vhdl_flux_alpha - ref_state.flux_alpha)
            errors_flux_beta.append(vhdl_flux_beta  - ref_state.flux_beta)
            errors_speed.append(vhdl_speed         - ref_state.speed_mech)
            refs_i_alpha.append(ref_state.i_alpha)
            refs_i_beta.append(ref_state.i_beta)

            rows.append({
                "step":             step,
                "t_us":             round(t_us, 4),
                "va":               round(va, 6),
                "vb":               round(vb, 6),
                "vc":               round(vc, 6),
                "f_ref_hz":         0.0,
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

            if step in (WARMUP_STEPS, WARMUP_STEPS + 1, WARMUP_STEPS + 10):
                dut._log.info(
                    "step=%d | vhdl(iα,iβ,ψα,ψβ)=(%.6f, %.6f, %.6f, %.6f) "
                    "ref=(%.6f, %.6f, %.6f, %.6f)",
                    step,
                    vhdl_i_alpha, vhdl_i_beta, vhdl_flux_alpha, vhdl_flux_beta,
                    ref_state.i_alpha, ref_state.i_beta,
                    ref_state.flux_alpha, ref_state.flux_beta,
                )

    assert rows, "No comparison samples collected"

    # ── Metrics ──────────────────────────────────────────────────────────────
    nrmse_i_alpha  = rms(errors_i_alpha) / max(rms(refs_i_alpha), 1e-9)
    nrmse_i_beta   = rms(errors_i_beta)  / max(rms(refs_i_beta),  1e-9)
    mae_flux_alpha = sum(abs(v) for v in errors_flux_alpha) / len(errors_flux_alpha)
    mae_flux_beta  = sum(abs(v) for v in errors_flux_beta)  / len(errors_flux_beta)
    mae_speed      = sum(abs(v) for v in errors_speed)      / len(errors_speed)

    dut._log.info("Reference comparison metrics:")
    dut._log.info(f"  NRMSE i_alpha  = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta   = {nrmse_i_beta:.6f}")
    dut._log.info(f"  MAE flux_alpha = {mae_flux_alpha:.2e} Wb")
    dut._log.info(f"  MAE flux_beta  = {mae_flux_beta:.2e} Wb")
    dut._log.info(f"  MAE speed_mech = {mae_speed:.6f} rad/s")

    assert nrmse_i_alpha  < 0.10,  f"i_alpha NRMSE={nrmse_i_alpha:.6f}"
    assert nrmse_i_beta   < 0.10,  f"i_beta  NRMSE={nrmse_i_beta:.6f}"
    assert mae_flux_alpha < 1e-3,  f"flux_alpha MAE={mae_flux_alpha:.2e} Wb"
    assert mae_flux_beta  < 1e-3,  f"flux_beta  MAE={mae_flux_beta:.2e} Wb"
    assert mae_speed      < 2.0,   f"speed MAE={mae_speed:.6f} rad/s"

    # ── Save CSV ─────────────────────────────────────────────────────────────
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    dut._log.info(f"CSV saved: {CSV_PATH} ({len(rows)} rows)")

    # ── Generate HTML report ─────────────────────────────────────────────────
    dut._log.info("Generating HTML report...")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "vf_report.py"),
            "--compare-only",
            "--vhdl-csv", str(CSV_PATH),
            "--out",      str(HTML_PATH),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        dut._log.info(f"Report saved: {HTML_PATH}")
    else:
        dut._log.warning(f"Report generation failed:\n{result.stderr}")
