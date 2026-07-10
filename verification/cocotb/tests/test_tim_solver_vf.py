"""V/F (Volt/Hertz) stimulus test for TIM_Solver — full 1.5 s run.

Drives the VHDL with a realistic open-loop V/F ramp (60 Hz/s, matching PSIM)
and records results for the HTML overlay report.

Progress is printed to stdout every 1 % of simulation time so that long runs
can be monitored live (e.g. `tail -f sim_build/vf_progress.log`).

Results are saved to reports/vf_vhdl_vs_ref.csv (decimated: 1 row per
RECORD_INTERVAL motor steps so the file stays manageable).
"""

import csv
import json
import math
import os
import time
from pathlib import Path

INITIAL_THETA = math.pi / 4  # 45° offset — ensures both α and β channels are excited

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.sim_benchmark import save_benchmark
from models.transient_metrics import compute_transient_metrics
from models.vf_control import VFControl


DATA_WIDTH       = 42
FP_FRACTION_BITS = 28
FP_SCALE         = 1 << FP_FRACTION_BITS

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw in (None, "") else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw in (None, "") else int(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return default if raw in (None, "") else Path(raw)


def _env_float_opt(name: str) -> float | None:
    raw = os.environ.get(name)
    return None if raw in (None, "") else float(raw)


# ── Simulation extent ─────────────────────────────────────────────────────────
SIM_DURATION_S  = _env_float("HIL_VF_DURATION_S", 1.5)
CLOCK_FREQUENCY = _env_int("IM_CLOCK_FREQUENCY", 200_000_000)
SOLVER_STEP_CYCLES = _env_int("IM_SOLVER_STEP_CYCLES", 26)
TS_S            = _env_float("IM_TS", SOLVER_STEP_CYCLES / CLOCK_FREQUENCY)
CLK_PERIOD_PS   = int(round(1e12 / CLOCK_FREQUENCY))
SIM_STEPS       = int(SIM_DURATION_S / TS_S)

WARMUP_STEPS    = _env_int("HIL_VF_WARMUP_STEPS", 200)

# ── Clock / timer constants ───────────────────────────────────────────────────
# CLOCK_FREQUENCY=200 MHz x Ts=130 ns -> exactly 26 clock cycles per motor step.
# After the first wait_data_valid sync, data_valid fires every TIMER_STEPS cycles,
# unless the solver overruns.
TIMER_STEPS     = int(CLOCK_FREQUENCY * TS_S)

# ── V/F control parameters ───────────────────────────────────────────────────
F_NOMINAL_HZ    = _env_float("HIL_VF_F_NOMINAL_HZ", 60.0)
V_PEAK_NOMINAL  = _env_float("HIL_VF_V_PEAK_NOMINAL", 620.0)
ACC_RAMP_HZ_S   = _env_float("HIL_VF_ACC_RAMP_HZ_S", 60.0)
TLOAD_NM        = _env_float("HIL_VF_TLOAD_NM", 0.0)
TLOAD_STEP_NM       = _env_float_opt("HIL_VF_TLOAD_STEP_NM")
TLOAD_STEP_TIME_S   = _env_float_opt("HIL_VF_TLOAD_STEP_TIME_S")
INITIAL_THETA   = _env_float("HIL_VF_INITIAL_THETA_RAD", INITIAL_THETA)

# ── Recording / progress ──────────────────────────────────────────────────────
RECORD_INTERVAL  = _env_int("HIL_VF_RECORD_INTERVAL", 400)
PROGRESS_EVERY   = max(1, SIM_STEPS // 100)

# ── Output paths ─────────────────────────────────────────────────────────────
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
CSV_PATH    = _env_path("HIL_VF_CSV", REPORTS_DIR / "vf_vhdl_vs_ref.csv")
METRICS_PATH = _env_path("HIL_VF_METRICS", REPORTS_DIR / "vf_metrics.json")


# ── Fixed-point helpers ───────────────────────────────────────────────────────

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
        raise AssertionError(
            f"Signal {signal._name} is unresolved: {raw.binstr}"
        ) from exc
    return signed / float(FP_SCALE)


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def _rpm(rad_s: float) -> float:
    return rad_s * 60.0 / (2.0 * math.pi)


# ── DUT helpers ───────────────────────────────────────────────────────────────

async def reset_dut(dut, cycles: int = 20) -> None:
    dut.reset_n.value       = 0
    dut.va_i.value          = 0
    dut.vb_i.value          = 0
    dut.vc_i.value          = 0
    dut.torque_load_i.value = 0
    dut.state_clear_i.value = 0
    dut.coeff_we_i.value = 0
    dut.coeff_apply_i.value = 0
    dut.coeff_matrix_i.value = 0
    dut.coeff_row_i.value = 0
    dut.coeff_col_i.value = 0
    dut.coeff_data_i.value = 0
    await ClockCycles(dut.sysclk, cycles)
    dut.reset_n.value = 1
    await ClockCycles(dut.sysclk, 5)


async def wait_data_valid(dut) -> None:
    while True:
        await RisingEdge(dut.sysclk)
        if int(dut.data_valid_o.value) == 1:
            return


# ── Progress helper ───────────────────────────────────────────────────────────

def _print_progress(
    step: int,
    t_s: float,
    f_hz: float,
    i_alpha: float,
    speed_mech: float,
    t_start: float,
) -> None:
    """Print a one-line progress update with ETA to stdout (unbuffered)."""
    pct      = 100.0 * step / SIM_STEPS
    elapsed  = time.monotonic() - t_start
    rate     = step / elapsed if elapsed > 0 else 0.0
    remaining = (SIM_STEPS - step) / rate if rate > 0 else float("inf")

    if remaining == float("inf"):
        eta_str = "  --.-s"
    elif remaining >= 3600:
        eta_str = f"{remaining/3600:6.2f}h"
    elif remaining >= 60:
        eta_str = f"{remaining/60:5.1f}min"
    else:
        eta_str = f"{remaining:6.1f}s"

    print(
        f"[VF {pct:5.1f}%] "
        f"t={t_s:6.3f}s  "
        f"f={f_hz:5.1f}Hz  "
        f"ωm={_rpm(speed_mech):8.1f}RPM  "
        f"iα={i_alpha:8.3f}A  "
        f"elapsed={elapsed:7.1f}s  "
        f"ETA={eta_str}",
        flush=True,
    )


# ── Test ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_tim_solver_vf_stimulus(dut):
    """Drive TIM_Solver with a 1.5 s V/F ramp and compare against C reference."""

    clock = Clock(dut.sysclk, CLK_PERIOD_PS, unit="ps")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    params = IMPhysicalParams.defaults()
    ref    = InductionMotorReferenceModel(params=params, backend="auto")
    dut._log.info(f"Reference backend: {ref.backend_name}")

    vf = VFControl(
        f_nominal     = F_NOMINAL_HZ,
        v_peak_nominal= V_PEAK_NOMINAL,
        acc_ramp_hz_s = ACC_RAMP_HZ_S,
        ts            = params.ts,
        tload         = TLOAD_NM,
        initial_theta = INITIAL_THETA,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    errors_i_alpha: list[float] = []
    errors_i_beta:  list[float] = []
    rows: list[dict] = []

    # ── Batch loop ────────────────────────────────────────────────────────────
    # Instead of driving VHDL step-by-step (1 GPI await per 100 ns motor step),
    # we process RECORD_INTERVAL steps per Python iteration:
    #   - Apply V/F input once  (constant over the batch — V/F changes <0.004%)
    #   - Await TIMER_STEPS × RECORD_INTERVAL clock cycles  (1 GPI call)
    #   - Read 5 outputs once
    #   - Run C reference RECORD_INTERVAL times with the same constant input
    # Both VHDL and C reference see identical inputs → valid comparison.
    # GPI calls: 10 per batch × 37,500 batches ≈ 1 minute vs 6+ hours before.

    N_BATCHES        = SIM_STEPS // RECORD_INTERVAL          # 37,500
    PROGRESS_BATCHES = max(1, N_BATCHES // 100)             # print every 1 %
    # Timer advances simulation time in ONE GPI call (unlike ClockCycles which
    # yields once per clock edge).  Each batch = RECORD_INTERVAL × Ts = 40 µs.
    BATCH_TIME_NS    = int(RECORD_INTERVAL * TS_S * 1e9)    # 400 × 100 ns = 40 000 ns

    dut._log.info(
        f"V/F simulation: {SIM_STEPS:,} steps ({SIM_DURATION_S:.3f} s motor time)  "
        f"batch={RECORD_INTERVAL} steps  {N_BATCHES:,} batches"
    )
    dut._log.info(
        "V/F parameters: "
        f"f_nom={F_NOMINAL_HZ:g}Hz v_peak={V_PEAK_NOMINAL:g}V "
        f"acc={ACC_RAMP_HZ_S:g}Hz/s tload={TLOAD_NM:g}Nm theta0={INITIAL_THETA:g}rad"
    )
    dut._log.info(
        "Motor parameters: "
        f"Rs={params.rs:g} Rr={params.rr:g} Ls={params.ls:g} Lr={params.lr:g} "
        f"Lm={params.lm:g} J={params.j:g} npp={params.npp:g} Ts={params.ts:g}"
    )
    dut._log.info(
        f"Simulation clock: {CLOCK_FREQUENCY} Hz, period={CLK_PERIOD_PS} ps, "
        f"solver_step_cycles={SOLVER_STEP_CYCLES}, timer_steps={TIMER_STEPS}"
    )
    print(
        f"\n[VF] Starting: {SIM_STEPS:,} steps ({SIM_DURATION_S:.3f} s)  "
        f"ACC={ACC_RAMP_HZ_S} Hz/s  Tload={TLOAD_NM} Nm  "
        f"batch={RECORD_INTERVAL} steps  {N_BATCHES:,} batches\n",
        flush=True,
    )

    t_start           = time.monotonic()
    last_vhdl_i_alpha = 0.0
    last_vhdl_speed   = 0.0

    for batch_idx in range(N_BATCHES):
        step = batch_idx * RECORD_INTERVAL

        # ── Advance V/F, sample at batch midpoint for best accuracy ──────────
        half = RECORD_INTERVAL // 2
        for _ in range(half):
            vf.step()
        va, vb, vc = vf.step()          # midpoint sample
        tload = vf.tload
        if (
            TLOAD_STEP_NM is not None
            and TLOAD_STEP_TIME_S is not None
            and step * TS_S >= TLOAD_STEP_TIME_S
        ):
            tload = TLOAD_STEP_NM
        for _ in range(RECORD_INTERVAL - half - 1):
            vf.step()                   # advance to batch end

        # ── Apply to VHDL (constant for this batch) ──────────────────────────
        dut.va_i.value          = signed_to_slv(real_to_fp(va),    DATA_WIDTH)
        dut.vb_i.value          = signed_to_slv(real_to_fp(vb),    DATA_WIDTH)
        dut.vc_i.value          = signed_to_slv(real_to_fp(vc),    DATA_WIDTH)
        dut.torque_load_i.value = signed_to_slv(real_to_fp(tload), DATA_WIDTH)

        # ── Advance simulator — ONE GPI call jumps BATCH_TIME_NS forward ────
        # Timer(n, "ns") is a single GPI event (not N edge callbacks).
        # After the initial sync, data_valid is periodic, so we land correctly.
        if batch_idx == 0:
            await wait_data_valid(dut)      # initial sync (polling)
        await Timer(BATCH_TIME_NS, "ns")

        # ── Read VHDL outputs once per batch ─────────────────────────────────
        vhdl_i_alpha    = signal_fp_to_real(dut.ialpha_o)
        vhdl_i_beta     = signal_fp_to_real(dut.ibeta_o)
        vhdl_flux_alpha = signal_fp_to_real(dut.flux_rotor_alpha_o)
        vhdl_flux_beta  = signal_fp_to_real(dut.flux_rotor_beta_o)
        vhdl_speed      = signal_fp_to_real(dut.speed_mech_o)

        # ── Advance C reference RECORD_INTERVAL steps (same constant input) ──
        for _ in range(RECORD_INTERVAL):
            ref_state = ref.step(va, vb, vc, tload)

        # ── Cache for progress ────────────────────────────────────────────────
        last_vhdl_i_alpha = vhdl_i_alpha
        last_vhdl_speed   = vhdl_speed

        # ── Progress ─────────────────────────────────────────────────────────
        if batch_idx % PROGRESS_BATCHES == 0:
            _print_progress(
                step, step * TS_S, vf.f_ref,
                last_vhdl_i_alpha, last_vhdl_speed, t_start,
            )

        # ── Collect metrics and CSV row ───────────────────────────────────────
        errors_i_alpha.append(vhdl_i_alpha - ref_state.i_alpha)
        errors_i_beta.append(vhdl_i_beta   - ref_state.i_beta)

        rows.append({
            "step":            step,
            "t_us":            round(step * TS_S * 1e6, 4),
            "va":              round(va, 6),
            "vb":              round(vb, 6),
            "vc":              round(vc, 6),
            "f_ref_hz":        round(vf.f_ref, 4),
            # VHDL
            "vhdl_i_alpha":    vhdl_i_alpha,
            "vhdl_i_beta":     vhdl_i_beta,
            "vhdl_flux_alpha": vhdl_flux_alpha,
            "vhdl_flux_beta":  vhdl_flux_beta,
            "vhdl_speed":      vhdl_speed,
            # Reference
            "ref_i_alpha":     ref_state.i_alpha,
            "ref_i_beta":      ref_state.i_beta,
            "ref_flux_alpha":  ref_state.flux_alpha,
            "ref_flux_beta":   ref_state.flux_beta,
            "ref_speed":       ref_state.speed_mech,
        })

    # Final progress line
    _print_progress(
        SIM_STEPS, SIM_DURATION_S, vf.f_ref,
        last_vhdl_i_alpha, last_vhdl_speed, t_start,
    )
    dut._log.info(f"Batches completed: {N_BATCHES:,}  CSV rows: {len(rows):,}")

    wall_time = time.monotonic() - t_start
    msteps_per_s = SIM_STEPS / wall_time / 1e6
    print(
        f"\n[VF] Done in {wall_time:.1f}s wall time  "
        f"({msteps_per_s:.2f} Msteps/s)\n",
        flush=True,
    )

    # ── Write CSV ──────────────────────────────────────────────────────────────
    if rows:
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CSV_PATH.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        dut._log.info(f"CSV saved: {CSV_PATH} ({len(rows)} rows)")

    # ── Metrics ────────────────────────────────────────────────────────────────
    nrmse_i_alpha = rms(errors_i_alpha) / max(
        rms([r["ref_i_alpha"] for r in rows]), 1e-9
    )
    nrmse_i_beta = rms(errors_i_beta) / max(
        rms([r["ref_i_beta"] for r in rows]), 1e-9
    )

    mae_flux_alpha = sum(abs(r["vhdl_flux_alpha"] - r["ref_flux_alpha"]) for r in rows) / len(rows)
    mae_flux_beta  = sum(abs(r["vhdl_flux_beta"]  - r["ref_flux_beta"])  for r in rows) / len(rows)
    mae_speed      = sum(abs(r["vhdl_speed"]       - r["ref_speed"])       for r in rows) / len(rows)

    metrics = {
        "level": "L2",
        "test": "tim_solver_vf",
        "simulator": os.environ.get("SIM", "nvc"),
        "duration_s": SIM_DURATION_S,
        "sim_steps": SIM_STEPS,
        "record_interval_steps": RECORD_INTERVAL,
        "clock_frequency_hz": CLOCK_FREQUENCY,
        "solver_step_cycles": SOLVER_STEP_CYCLES,
        "clock_period_ps": CLK_PERIOD_PS,
        "csv_rows": len(rows),
        "vf": {
            "f_nominal_hz": F_NOMINAL_HZ,
            "v_peak_nominal_v": V_PEAK_NOMINAL,
            "acc_ramp_hz_s": ACC_RAMP_HZ_S,
            "t_acc_s": F_NOMINAL_HZ / ACC_RAMP_HZ_S if ACC_RAMP_HZ_S else None,
            "tload_nm": TLOAD_NM,
            "initial_theta_rad": INITIAL_THETA,
        },
        "motor": {
            "rs": params.rs, "rr": params.rr, "ls": params.ls, "lr": params.lr,
            "lm": params.lm, "j": params.j, "npp": params.npp, "ts": params.ts,
        },
        "metrics": {
            "nrmse_i_alpha": nrmse_i_alpha,
            "nrmse_i_beta": nrmse_i_beta,
            "mae_flux_alpha_wb": mae_flux_alpha,
            "mae_flux_beta_wb": mae_flux_beta,
            "mae_speed_rad_s": mae_speed,
            "mae_speed_rpm": _rpm(mae_speed),
        },
    }
    if TLOAD_STEP_NM is not None and TLOAD_STEP_TIME_S is not None:
        t_arr = [r["t_us"] / 1e6 for r in rows]
        metrics["transient"] = {
            "vhdl": compute_transient_metrics(
                t_arr, [r["vhdl_speed"] for r in rows],
                [r["vhdl_i_alpha"] for r in rows], [r["vhdl_i_beta"] for r in rows],
                TLOAD_STEP_TIME_S,
            ),
            "c": compute_transient_metrics(
                t_arr, [r["ref_speed"] for r in rows],
                [r["ref_i_alpha"] for r in rows], [r["ref_i_beta"] for r in rows],
                TLOAD_STEP_TIME_S,
            ),
        }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))

    dut._log.info(f"VHDL vs C Reference — {SIM_DURATION_S:.3f}s V/F run")
    dut._log.info(f"  NRMSE i_alpha  = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta   = {nrmse_i_beta:.6f}")
    dut._log.info(f"  MAE flux_alpha = {mae_flux_alpha:.2e} Wb")
    dut._log.info(f"  MAE flux_beta  = {mae_flux_beta:.2e} Wb")
    dut._log.info(f"  MAE speed_mech = {mae_speed:.4f} rad/s ({_rpm(mae_speed):.2f} RPM)")
    dut._log.info(f"Metrics saved: {METRICS_PATH}")

    assert nrmse_i_alpha < 0.10, f"i_alpha mismatch: {nrmse_i_alpha:.6f}"
    assert nrmse_i_beta  < 0.10, f"i_beta  mismatch: {nrmse_i_beta:.6f}"
    assert mae_flux_alpha < 1e-2, f"flux_alpha MAE={mae_flux_alpha:.2e}"
    assert mae_flux_beta  < 1e-2, f"flux_beta  MAE={mae_flux_beta:.2e}"
    assert mae_speed      < 5.0,  f"speed MAE={mae_speed:.4f} rad/s"

    # ── Save benchmark ────────────────────────────────────────────────────────
    save_benchmark(
        test_name   = "tim_solver_vf",
        sim_steps   = SIM_STEPS,
        ts_s        = TS_S,
        wall_time_s = wall_time,
        extra       = {
            "nrmse_i_alpha":    round(nrmse_i_alpha,  6),
            "nrmse_i_beta":     round(nrmse_i_beta,   6),
            "mae_flux_alpha_wb":round(mae_flux_alpha, 6),
            "mae_flux_beta_wb": round(mae_flux_beta,  6),
            "mae_speed_rad_s":  round(mae_speed,      4),
            "batch_size":       RECORD_INTERVAL,
        },
    )
