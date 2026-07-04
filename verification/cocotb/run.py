"""
cocotb Runner — Top_HIL testbench.

Supports GHDL and NVC simulators.  Select with --sim:

    uv run python run.py --sim ghdl   # default
    uv run python run.py --sim nvc    # faster (requires NVC ≥ 1.13)

Usage:
    uv run python run.py                              # all tests, ghdl
    uv run python run.py --sim nvc --top tim_solver   # NVC, TIM_Solver
    uv run python run.py -k test_write_read_vdc_bus   # single test
    uv run python run.py --waves                      # waveform dump
"""

import argparse
import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner


# ---------------------------------------------------------------------------
# Simulator configuration
# ---------------------------------------------------------------------------

# Build-time args per simulator (analysis / elaboration flags)
BUILD_ARGS = {
    "ghdl": ["--std=08"],
    "nvc":  ["--std=2008"],
}

# Run-time args per simulator
RUN_ARGS = {
    "ghdl": ["--std=08"],
    "nvc":  [],
}

# Waveform flag per simulator (format: <flag_template>, <file_extension>)
# These are simulator runtime args, NOT VPI plusargs — passed via test_args.
# GHDL: --wave generates GHW (full hierarchy); --vcd only captures top ports.
# NVC:  --wave generates FST (full hierarchy).
WAVE_FLAG = {
    "ghdl": ("--wave={path}", ".ghw"),
    "nvc":  ("--wave={path}", ".fst"),
}


# ---------------------------------------------------------------------------
# VHDL source lists
# ---------------------------------------------------------------------------

def get_vhdl_sources(top: str) -> list[Path]:
    """Return VHDL source files in dependency order for a selected top-level."""
    project_root = Path(__file__).resolve().parent.parent.parent
    common = project_root / "common" / "modules"
    tb_hdl = Path(__file__).resolve().parent / "hdl"

    if top == "clarke_transform":
        sources = [
            tb_hdl / "ClarkeMultiplier_DSP.vhd",
            common / "clarke_transform" / "src" / "ClarkeTransform.vhd",
        ]

    elif top == "bilinear_solver":
        # BilinearSolverUnitTB wraps the DUT to expose scalar ports for VPI.
        sources = [
            common / "bilinear_solver" / "src" / "BilinearSolverPkg.vhd",
            common / "bilinear_solver" / "src" / "BilienarSolverUnit_DSP.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverUnit.vhd",
            tb_hdl / "BilinearSolverUnitTB.vhd",
        ]

    elif top == "top_hil":
        sources = [
            common / "bilinear_solver" / "src" / "BilinearSolverPkg.vhd",
            common / "bilinear_solver" / "src" / "BilienarSolverUnit_DSP.vhd",
            common / "fifo"            / "src" / "fifo.vhd",
            common / "uart"            / "src" / "UartTX.vhd",
            common / "uart"            / "src" / "UartRX.vhd",
            common / "edge_detector"   / "src" / "EdgeDetector.vhd",
            tb_hdl / "ClarkeMultiplier_DSP.vhd",
            common / "clarke_transform"/ "src" / "ClarkeTransform.vhd",
            common / "uart"            / "src" / "UartFull.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverUnit.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverHandler.vhd",
            common / "npc_modulator"   / "src" / "NPCModulator.vhd",
            common / "npc_modulator"   / "src" / "NPCGateDriver.vhd",
            common / "npc_modulator"   / "src" / "NPCManager.vhd",
            project_root / "src" / "rtl" / "SerialManager.vhd",
            project_root / "src" / "rtl" / "TIM_Solver.vhd",
            project_root / "src" / "rtl" / "Top_HIL.vhd",
        ]

    elif top == "tim_solver":
        sources = [
            common / "bilinear_solver" / "src" / "BilinearSolverPkg.vhd",
            common / "bilinear_solver" / "src" / "BilienarSolverUnit_DSP.vhd",
            common / "edge_detector"   / "src" / "EdgeDetector.vhd",
            tb_hdl / "ClarkeMultiplier_DSP.vhd",
            common / "clarke_transform"/ "src" / "ClarkeTransform.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverUnit.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverHandler.vhd",
            project_root / "src" / "rtl" / "TIM_Solver.vhd",
        ]

    else:
        raise ValueError(f"Unsupported top-level: {top!r}")

    for src in sources:
        if not src.exists():
            print(f"ERROR: VHDL source not found: {src}", file=sys.stderr)
            sys.exit(1)

    return sources


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run cocotb tests — supports GHDL and NVC simulators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Simulators:
  ghdl  — default, widely available (apt install ghdl)
  nvc   — faster; see: https://github.com/nickg/nvc/releases
           Ubuntu quick-install: make setup-nvc  (from verification/cocotb/)

Examples:
  uv run python run.py                              # all tests, GHDL
  uv run python run.py --sim nvc                    # all tests, NVC
  uv run python run.py --sim nvc --top tim_solver --test vf
  uv run python run.py -k test_pwm_enable --waves
""",
    )
    parser.add_argument(
        "--sim",
        type=str,
        default="ghdl",
        choices=["ghdl", "nvc"],
        help="Simulator backend (default: ghdl)",
    )
    parser.add_argument(
        "--top",
        type=str,
        default="top_hil",
        choices=["top_hil", "tim_solver", "clarke_transform", "bilinear_solver"],
        help="Top-level DUT (default: top_hil)",
    )
    parser.add_argument(
        "--test",
        type=str,
        default=None,
        choices=["reference", "vf", "sine"],
        help="Test suite for tim_solver (default: reference)",
    )
    parser.add_argument(
        "-k", "--testcase",
        type=str,
        default=None,
        help="Run only the named test function",
    )
    parser.add_argument(
        "--waves",
        action="store_true",
        help="Enable waveform dump (VCD for GHDL, FST for NVC)",
    )
    parser.add_argument(
        "--build-dir",
        type=str,
        default="sim_build",
        help="Build directory (default: sim_build)",
    )
    args = parser.parse_args()

    sim = args.sim

    # Ensure the test module's directory is importable
    tb_dir = Path(__file__).resolve().parent
    if str(tb_dir) not in sys.path:
        sys.path.insert(0, str(tb_dir))

    runner = get_runner(sim)

    # Entity names (VHDL entity as seen by VPI — always lowercase)
    ENTITY_NAME = {
        "top_hil":          "top_hil",
        "tim_solver":       "tim_solver",
        "clarke_transform": "clarketransform",
        "bilinear_solver":  "bilinearsolverunittb",
    }
    entity = ENTITY_NAME[args.top]
    sources = get_vhdl_sources(args.top)

    # ── Per-DUT configuration ────────────────────────────────────────────
    if args.top == "clarke_transform":
        test_module    = "tests.test_clarke_transform"
        sim_parameters = {"DATA_WIDTH": 42, "FRAC_WIDTH": 28}

    elif args.top == "bilinear_solver":
        test_module    = "tests.test_bilinear_solver"
        sim_parameters = {}

    elif args.top == "top_hil":
        test_module    = "tests.test_top_hil"

        def env_float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return default if raw in (None, "") else float(raw)

        def env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return default if raw in (None, "") else int(raw)

        sim_parameters = {
            "CLK_FREQUENCY": env_int("IM_CLOCK_FREQUENCY", 200_000_000),
            "PWM_FREQUENCY": env_int("HIL_PWM_FREQUENCY", 1_000),
            "SOLVER_STEP_CYCLES": env_int("IM_SOLVER_STEP_CYCLES", 26),
            "MOTOR_RS": env_float("IM_RS", 0.4396),
            "MOTOR_RR": env_float("IM_RR", 0.2826),
            "MOTOR_LS": env_float("IM_LS", 3.1364e-3),
            "MOTOR_LR": env_float("IM_LR", 6.3264e-3),
            "MOTOR_LM": env_float("IM_LM", 109.9442e-3),
            "MOTOR_J": env_float("IM_J", 0.4),
            "MOTOR_NPP": env_float("IM_NPP", 2.0),
            "BAUD_RATE": env_int("HIL_UART_BAUD", 1_000_000),
        }

    else:  # tim_solver
        test_suite  = args.test or "reference"
        test_module = {
            "reference": "tests.test_tim_solver_reference",
            "vf":        "tests.test_tim_solver_vf",
            "sine":      "tests.test_tim_solver_sine",
        }[test_suite]

        def env_float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return default if raw in (None, "") else float(raw)

        def env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return default if raw in (None, "") else int(raw)

        # Hardware target: 200 MHz solver clock, 26 clocks per motor step.
        # Motor generics are overridable so L2 can be run with the exact same
        # parameter set as the synthesized HIL_AXI_Top or a PSIM reference case.
        sim_parameters = {
            "CLOCK_FREQUENCY": env_int("IM_CLOCK_FREQUENCY", 200_000_000),
            "SOLVER_STEP_CYCLES": env_int("IM_SOLVER_STEP_CYCLES", 26),
            "rs": env_float("IM_RS", 0.4396),
            "rr": env_float("IM_RR", 0.2826),
            "ls": env_float("IM_LS", 3.1364e-3),
            "lr": env_float("IM_LR", 6.3264e-3),
            "lm": env_float("IM_LM", 109.9442e-3),
            "j": env_float("IM_J", 0.4),
            "npp": env_float("IM_NPP", 2.0),
        }

    # ── Waveform setup ───────────────────────────────────────────────────
    # Wave flags are simulator runtime args → go in test_args, NOT plusargs.
    # (plusargs are forwarded with '+' prefix which GHDL/NVC do not understand)
    run_args = list(RUN_ARGS[sim])
    if args.waves:
        flag_tpl, ext = WAVE_FLAG[sim]
        wave_path = (tb_dir / args.build_dir / f"waves_{args.top}{ext}").resolve()
        run_args.append(flag_tpl.format(path=wave_path))
        print(f"Waveform → {wave_path}")

    # ── Build ────────────────────────────────────────────────────────────
    runner.build(
        sources=[str(s) for s in sources],
        hdl_toplevel=entity,
        build_dir=args.build_dir,
        build_args=BUILD_ARGS[sim],
        always=True,
    )

    # ── Run ─────────────────────────────────────────────────────────────
    runner.test(
        hdl_toplevel=entity,
        test_module=test_module,
        build_dir=args.build_dir,
        hdl_toplevel_lang="vhdl",
        testcase=args.testcase if args.testcase else None,
        test_args=run_args,
        parameters=sim_parameters,
    )


if __name__ == "__main__":
    main()
