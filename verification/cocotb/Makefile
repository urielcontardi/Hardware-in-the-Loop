# =============================================================================
# Makefile — cocotb Testbench (GHDL or NVC backend)
# =============================================================================
#
# Simulator selection (override with SIM=nvc for faster simulation):
#   make SIM=ghdl   — default, uses GHDL (apt install ghdl)
#   make SIM=nvc    — faster;  install with: make setup-nvc
#
# Usage (from project root):
#   make cocotb                                         - Run all cocotb tests
#   make cocotb SIM=nvc                                 - Run with NVC
#   make cocotb TESTCASE=test_write_read_vdc_bus        - Run a single test
#
# Usage (from this directory):
#   make                        - Run all tests (GHDL)
#   make SIM=nvc                - Run all tests (NVC)
#   make test TOP=tim_solver    - TIM_Solver tests
#   make waves                  - Run + waveform dump
#   make setup                  - Install Python deps via uv
#   make setup-nvc              - Install NVC from GitHub release
#
# Prerequisites:
#   - GHDL ≥ 4.0  (with VPI support)  or  NVC ≥ 1.13
#   - uv   (Python package manager: https://docs.astral.sh/uv/)
#
# =============================================================================

# ── Tools ───────────────────────────────────────────────────────────────
UV       ?= uv
GTKWAVE  ?= gtkwave

# ── Test configuration ──────────────────────────────────────────────────
SIM      ?= ghdl
TESTCASE ?=
TOP      ?= top_hil

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
	@echo "Installing Python dependencies with uv..."
	$(UV) sync

# ── Setup: install NVC from GitHub release (.deb for Ubuntu 24.04) ──────
NVC_VERSION ?= 1.19.3
NVC_DEB      = nvc_$(NVC_VERSION)-1_amd64.deb
NVC_URL      = https://github.com/nickg/nvc/releases/download/r$(NVC_VERSION)/$(NVC_DEB)

.PHONY: setup-nvc
setup-nvc:
	@echo ""
	@echo "Installing NVC $(NVC_VERSION) (Ubuntu 24.04 .deb)..."
	@cd /tmp && curl -fsSL $(NVC_URL) -o nvc.deb && sudo dpkg -i nvc.deb
	@nvc --version
	@echo "NVC installed. Run with: make SIM=nvc"

# ── Run all tests ───────────────────────────────────────────────────────
.PHONY: test
test:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     cocotb: Top_HIL Testbench ($(SIM))        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --top $(TOP) $(TEST_ARGS)

# ── Run tests with waveform dump ────────────────────────────────────────
.PHONY: waves
WAVE_EXT_ghdl = ghw
WAVE_EXT_nvc  = fst
WAVE_EXT      = $(WAVE_EXT_$(SIM))

waves:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║   cocotb: $(TOP) + Waveforms ($(SIM))         ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --top $(TOP) --waves $(TEST_ARGS)
	@echo "Opening GTKWave..."
	$(GTKWAVE) sim_build/waves_$(TOP).$(WAVE_EXT) &

# ── TIM_Solver reference model comparison ───────────────────────────────
.PHONY: tim-ref
tim-ref:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ cocotb: TIM_Solver vs C Reference ($(SIM))    ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --top tim_solver -k test_tim_solver_matches_reference_model

.PHONY: tim-vf
tim-vf:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ cocotb: TIM_Solver V/F stimulus ($(SIM))      ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --top tim_solver --test vf -k test_tim_solver_vf_stimulus

# ── TIM_Solver V/F — background run with live log monitoring ─────────────────
VF_LOG ?= sim_build/vf_progress.log

.PHONY: tim-vf-bg
tim-vf-bg:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ cocotb: TIM_Solver V/F — background ($(SIM)) ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@mkdir -p sim_build
	@echo "Starting background simulation → $(VF_LOG)"
	@nohup $(UV) run python run.py --sim $(SIM) --top tim_solver --test vf \
	    -k test_tim_solver_vf_stimulus > $(VF_LOG) 2>&1 &
	@echo "PID: $$!"
	@echo ""
	@echo "Monitor progress:"
	@echo "  tail -f $(VF_LOG)"
	@echo ""
	@echo "Or filter only the [VF] lines:"
	@echo "  tail -f $(VF_LOG) | grep '\\[VF'"
	@echo ""

.PHONY: report
report:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ Generating V/F HTML report (C ref only)      ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python scripts/vf_report.py

.PHONY: report-overlay
report-overlay:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ Generating V/F HTML report + VHDL overlay    ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python scripts/vf_report.py --overlay

.PHONY: tim-sine
tim-sine:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ cocotb: TIM_Solver pure sine 60 Hz ($(SIM))  ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python run.py --sim $(SIM) --top tim_solver --test sine

.PHONY: report-sine
report-sine:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║ Generating pure-sine HTML report + overlay   ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	$(UV) run python scripts/vf_report.py --sine --duration 0.2 --overlay \
	    --vhdl-csv reports/sine_vhdl_vs_ref.csv --out reports/sine_report.html

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
	@echo "║  Simulator (override with SIM=nvc):                     ║"
	@echo "║    make SIM=ghdl     Use GHDL (default)                 ║"
	@echo "║    make SIM=nvc      Use NVC  (faster)                  ║"
	@echo "║                                                         ║"
	@echo "║  Testing:                                               ║"
	@echo "║    make              Run all tests                      ║"
	@echo "║    make test TOP=<top> TESTCASE=<name>                  ║"
	@echo "║    make waves        Run tests + open GTKWave           ║"
	@echo "║    make tim-ref        TIM_Solver vs C ref (static)     ║"
	@echo "║    make tim-vf         TIM_Solver V/F ramp (foreground) ║"
	@echo "║    make tim-vf-bg      TIM_Solver V/F ramp (background) ║"
	@echo "║    make report         HTML report — C model only      ║"
	@echo "║    make report-overlay HTML report — C + VHDL overlay  ║"
	@echo "║                                                         ║"
	@echo "║  Setup:                                                 ║"
	@echo "║    make setup        Install Python deps via uv         ║"
	@echo "║    make setup-nvc    Install NVC simulator              ║"
	@echo "║    make clean        Remove build artifacts             ║"
	@echo "║    make help         Show this message                  ║"
	@echo "║                                                         ║"
	@echo "║  Available tests:                                       ║"
	@echo "║    test_write_read_vdc_bus                               ║"
	@echo "║    test_write_read_torque_load                           ║"
	@echo "║    test_read_all_registers                               ║"
	@echo "║    test_pwm_enable                                       ║"
	@echo "║    test_full_chain_motor_outputs                         ║"
	@echo "║    test_tim_solver_matches_reference_model (TOP=tim_solver) ║"
	@echo "║                                                         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
