# =============================================================================
# Makefile — cocotb Testbench for Top_HIL (GHDL backend)
# =============================================================================
#
# Location: verification/cocotb/
#
# Usage (from project root):
#   make cocotb                                         - Run all cocotb tests
#   make cocotb TESTCASE=test_write_read_vdc_bus        - Run a single test
#   make cocotb-waves                                   - Run + waveform dump
#
# Usage (from this directory):
#   make                                    - Run all cocotb tests
#   make test TESTCASE=test_write_read_vdc_bus  - Run a single test
#   make waves                              - Run all tests with waveform dump
#   make waves TESTCASE=test_full_chain_motor_outputs  - Single test + waves
#   make clean                              - Remove build artifacts
#   make setup                              - Install dependencies via uv
#
# Prerequisites:
#   - GHDL (with VPI support)
#   - uv   (Python package manager: https://docs.astral.sh/uv/)
#
# =============================================================================

# ── Tools ───────────────────────────────────────────────────────────────
UV       ?= uv
GTKWAVE  ?= gtkwave

# ── Test configuration ──────────────────────────────────────────────────
SIM      ?= ghdl
TESTCASE ?=

# Build test args
TEST_ARGS :=
ifneq ($(TESTCASE),)
	TEST_ARGS += -k $(TESTCASE)
endif

# ── Default target ──────────────────────────────────────────────────────
.PHONY: all
all: test

# ── Setup: install Python dependencies ──────────────────────────────────
.PHONY: setup
setup:
	@echo "Installing dependencies with uv..."
	$(UV) sync

# ── Run all tests ───────────────────────────────────────────────────────
.PHONY: test
test:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     cocotb: Top_HIL Testbench ($(SIM))        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) $(TEST_ARGS)

# ── Run tests with waveform dump ────────────────────────────────────────
.PHONY: waves
waves:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║   cocotb: Top_HIL + Waveforms ($(SIM))        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --waves $(TEST_ARGS)
	@echo "Opening GTKWave..."
	$(GTKWAVE) waves_top_hil.ghw &

# ── Clean build artifacts ──────────────────────────────────────────────
.PHONY: clean
clean:
	@echo "Cleaning build artifacts..."
	rm -rf sim_build
	rm -f results.xml
	rm -f *.ghw
	rm -rf __pycache__ tests/__pycache__ drivers/__pycache__
	@echo "Done."

# ── Help ────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║       cocotb Testbench — Available Targets              ║"
	@echo "╠══════════════════════════════════════════════════════════╣"
	@echo "║                                                         ║"
	@echo "║  Testing:                                               ║"
	@echo "║    make              Run all tests                      ║"
	@echo "║    make test         Run all tests                      ║"
	@echo "║    make test TESTCASE=<name>  Run a single test         ║"
	@echo "║    make waves        Run tests + open GTKWave           ║"
	@echo "║                                                         ║"
	@echo "║  Setup:                                                 ║"
	@echo "║    make setup        Install Python deps via uv         ║"
	@echo "║    make clean        Remove build artifacts             ║"
	@echo "║    make help         Show this message                  ║"
	@echo "║                                                         ║"
	@echo "║  Available tests:                                       ║"
	@echo "║    test_write_read_vdc_bus                               ║"
	@echo "║    test_write_read_torque_load                           ║"
	@echo "║    test_read_all_registers                               ║"
	@echo "║    test_pwm_enable                                       ║"
	@echo "║    test_full_chain_motor_outputs                         ║"
	@echo "║                                                         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
