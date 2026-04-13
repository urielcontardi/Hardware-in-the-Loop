"""V/F (Volt/Hertz) stimulus test for TIM_Solver — full 1.5 s run.

Drives the VHDL with a realistic open-loop V/F ramp (60 Hz/s, matching PSIM)
and records results for the HTML overlay report.

Progress is printed to stdout every 1 % of simulation time so that long runs
can be monitored live (e.g. `tail -f sim_build/vf_progress.log`).

Results are saved to reports/vf_vhdl_vs_ref.csv (decimated: 1 row per
RECORD_INTERVAL motor steps so the file stays manageable).
"""

import csv
import math
import time
from pathlib import Path

INITIAL_THETA = math.pi / 4  # 45° offset — ensures both α and β channels are excited

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.sim_benchmark import save_benchmark
from models.vf_control import VFControl


DATA_WIDTH       = 42
FP_FRACTION_BITS = 28
FP_SCALE         = 1 << FP_FRACTION_BITS

# ── Simulation extent ─────────────────────────────────────────────────────────
SIM_DURATION_S  = 1.5          # motor time  [s]
TS_S            = 40.0/150_000_000  # 266.67 ns — 40 cycles @ 150 MHz, must match VHDL generic
SIM_STEPS       = int(SIM_DURATION_S / TS_S)   # ~5 625 000 steps

WARMUP_STEPS    = 200          # steps discarded before recording / metrics

# ── Clock / timer constants ───────────────────────────────────────────────────
# CLOCK_FREQUENCY=150 MHz × Ts=266.67 ns → exactly 40 clock cycles per motor step.
# 150 MHz closes timing on Zynq-7010 -1 (critical path ~6.3 ns < 6.67 ns period).
# After the first wait_data_valid sync, data_valid fires every TIMER_STEPS cycles,
# so we can skip polling and jump directly — ~40× faster.
CLOCK_FREQUENCY = 150_000_000
TIMER_STEPS     = int(CLOCK_FREQUENCY * TS_S)   # 40

# ── V/F control parameters (matching PSIM setup) ─────────────────────────────
F_NOMINAL_HZ    = 60.0
V_PEAK_NOMINAL  = 620.0        # Phase peak voltage at f_nominal [V]
ACC_RAMP_HZ_S   = 60.0         # 60 Hz/s → nominal reached after 1 s
TLOAD_NM        = 0.0

# ── Recording / progress ──────────────────────────────────────────────────────
RECORD_INTERVAL  = 400         # save 1 CSV row per this many motor steps
PROGRESS_EVERY   = SIM_STEPS // 100   # print once per 1 % (= 150 000 steps)

# ── Output paths ─────────────────────────────────────────────────────────────
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
CSV_PATH    = REPORTS_DIR / "vf_vhdl_vs_ref.csv"


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

    clock = Clock(dut.sysclk, 6667, unit="ps")   # 150 MHz (6.667 ns) — matches CLOCK_FREQUENCY generic
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
        f"V/F simulation: {SIM_STEPS:,} steps ({SIM_DURATION_S:.1f} s motor time)  "
        f"batch={RECORD_INTERVAL} steps  {N_BATCHES:,} batches"
    )
    print(
        f"\n[VF] Starting: {SIM_STEPS:,} steps ({SIM_DURATION_S:.1f} s)  "
        f"ACC={ACC_RAMP_HZ_S} Hz/s  batch={RECORD_INTERVAL} steps  "
        f"{N_BATCHES:,} batches\n",
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

    dut._log.info(f"VHDL vs C Reference — {SIM_DURATION_S:.1f}s V/F run")
    dut._log.info(f"  NRMSE i_alpha  = {nrmse_i_alpha:.6f}")
    dut._log.info(f"  NRMSE i_beta   = {nrmse_i_beta:.6f}")
    dut._log.info(f"  MAE flux_alpha = {mae_flux_alpha:.2e} Wb")
    dut._log.info(f"  MAE flux_beta  = {mae_flux_beta:.2e} Wb")
    dut._log.info(f"  MAE speed_mech = {mae_speed:.4f} rad/s ({_rpm(mae_speed):.2f} RPM)")

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
