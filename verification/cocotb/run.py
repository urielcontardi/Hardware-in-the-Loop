"""
cocotb Runner for Top_HIL testbench (GHDL backend).

This uses the cocotb 2.x Python-based runner API instead of Makefile.sim,
which is more reliable with virtual environments and easier to extend.

Usage (from verification/cocotb/):
    uv run python run.py                              # Run all tests
    uv run python run.py -k test_write_read_vdc_bus   # Run single test
    uv run python run.py --waves                      # Enable waveform dump
"""

import argparse
import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner


def get_vhdl_sources(top: str) -> list[Path]:
    """Return VHDL source files in dependency order for a selected top-level."""
    project_root = Path(__file__).resolve().parent.parent.parent
    common = project_root / "common" / "modules"

    if top == "top_hil":
        sources = [
            # Packages (must be first)
            common / "bilinear_solver" / "src" / "BilinearSolverPkg.vhd",
            # DSP simulation stub (must be before BilinearSolverUnit)
            common / "bilinear_solver" / "src" / "BilienarSolverUnit_DSP.vhd",
            # Primitives
            common / "fifo" / "src" / "fifo.vhd",
            common / "uart" / "src" / "UartTX.vhd",
            common / "uart" / "src" / "UartRX.vhd",
            common / "edge_detector" / "src" / "EdgeDetector.vhd",
            common / "clarke_transform" / "src" / "ClarkeTransform.vhd",
            # Mid-level
            common / "uart" / "src" / "UartFull.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverUnit.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverHandler.vhd",
            common / "npc_modulator" / "src" / "NPCModulator.vhd",
            common / "npc_modulator" / "src" / "NPCGateDriver.vhd",
            common / "npc_modulator" / "src" / "NPCManager.vhd",
            # Project RTL
            project_root / "src" / "rtl" / "SerialManager.vhd",
            project_root / "src" / "rtl" / "TIM_Solver.vhd",
            project_root / "src" / "rtl" / "Top_HIL.vhd",
        ]
    elif top == "tim_solver":
        sources = [
            # Packages (must be first)
            common / "bilinear_solver" / "src" / "BilinearSolverPkg.vhd",
            # DSP simulation stub (must be before BilinearSolverUnit)
            common / "bilinear_solver" / "src" / "BilienarSolverUnit_DSP.vhd",
            # Primitives required by TIM_Solver
            common / "edge_detector" / "src" / "EdgeDetector.vhd",
            common / "clarke_transform" / "src" / "ClarkeTransform.vhd",
            # Bilinear solver modules
            common / "bilinear_solver" / "src" / "BilinearSolverUnit.vhd",
            common / "bilinear_solver" / "src" / "BilinearSolverHandler.vhd",
            # Project RTL under test
            project_root / "src" / "rtl" / "TIM_Solver.vhd",
        ]
    else:
        raise ValueError(f"Unsupported top-level: {top}")

    # Verify all sources exist
    for src in sources:
        if not src.exists():
            print(f"ERROR: VHDL source not found: {src}", file=sys.stderr)
            sys.exit(1)

    return sources


def main():
    parser = argparse.ArgumentParser(description="Run cocotb tests for Top_HIL")
    parser.add_argument(
        "-k", "--testcase",
        type=str,
        default=None,
        help="Run only the specified test function (e.g. test_write_read_vdc_bus)",
    )
    parser.add_argument(
        "--waves",
        action="store_true",
        help="Enable waveform dump (GHW format for GHDL)",
    )
    parser.add_argument(
        "--sim",
        type=str,
        default="ghdl",
        help="Simulator to use (default: ghdl)",
    )
    parser.add_argument(
        "--top",
        type=str,
        default="top_hil",
        choices=["top_hil", "tim_solver"],
        help="Top-level DUT to simulate (default: top_hil)",
    )
    parser.add_argument(
        "--test",
        type=str,
        default=None,
        choices=["reference", "vf"],
        help="Test suite to run for tim_solver (default: reference)",
    )
    parser.add_argument(
        "--build-dir",
        type=str,
        default="sim_build",
        help="Build directory (default: sim_build)",
    )
    args = parser.parse_args()

    # Ensure the test module's directory is importable
    tb_dir = Path(__file__).resolve().parent
    if str(tb_dir) not in sys.path:
        sys.path.insert(0, str(tb_dir))

    # Get the simulator runner
    runner = get_runner(args.sim)

    # VHDL sources
    sources = get_vhdl_sources(args.top)

    if args.top == "top_hil":
        test_module = "tests.test_top_hil"
        # Generic overrides for faster UART simulation
        sim_parameters = {
            "CLK_FREQUENCY": 100_000_000,   # 100 MHz
            "BAUD_RATE": 1_000_000,         # 1 Mbaud
        }
    else:
        # Select test suite
        test_suite = args.test or "reference"
        test_module = {
            "reference": "tests.test_tim_solver_reference",
            "vf":        "tests.test_tim_solver_vf",
        }[test_suite]

        # CLOCK_FREQUENCY must give TIMER_STEPS > solver pipeline latency.
        # With simulation DSP stub (LATENCY=7): total chain latency ~29 cycles.
        # 400 MHz × Ts=100ns → TIMER_STEPS=40, giving ~11-cycle margin.
        # The matrices are computed with Ts=100ns (default generic), so physics is correct.
        sim_parameters = {
            "CLOCK_FREQUENCY": 400_000_000,
        }

    # Build (analyze + elaborate)
    runner.build(
        sources=[str(s) for s in sources],
        hdl_toplevel=args.top,
        build_dir=args.build_dir,
        build_args=["--std=08"],
        always=True,
    )

    # Run
    test_args = ["--std=08"]
    plusargs = []
    if args.waves:
        vcd_path = (tb_dir / args.build_dir / "waves_top_hil.vcd").resolve()
        plusargs.append(f"--vcd={vcd_path}")

    runner.test(
        hdl_toplevel=args.top,
        test_module=test_module,
        build_dir=args.build_dir,
        hdl_toplevel_lang="vhdl",
        testcase=args.testcase if args.testcase else None,
        test_args=test_args,
        plusargs=plusargs,
        parameters=sim_parameters,
    )


if __name__ == "__main__":
    main()
