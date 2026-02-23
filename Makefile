# =============================================================================
# Makefile — Hardware-in-the-Loop (HIL) Project
# =============================================================================
#
# Usage:
#   make                    - Run SerialManager testbench (default)
#   make sim-serial         - Run SerialManager testbench
#   make sim-tim            - Run TIM Solver testbench
#   make sim-top            - Run Top_HIL testbench
#   make sim-all            - Run all VHDL testbenches
#   make wave-serial        - Run SerialManager and open GTKWave
#   make wave-tim           - Run TIM Solver and open GTKWave
#   make wave-top           - Run Top_HIL and open GTKWave
#   make compile            - Compile all sources (no sim)
#   make cocotb             - Run all cocotb (Python) tests
#   make cocotb TESTCASE=<name> - Run a single cocotb test
#   make cocotb-waves       - Run cocotb tests + waveform dump
#   make cocotb-setup       - Install cocotb Python dependencies
#   make clean              - Remove all generated files
#
# Dependencies:
#   - GHDL   (VHDL simulator, with VPI support for cocotb)
#   - GTKWave (waveform viewer, optional)
#   - uv     (Python package manager, for cocotb tests)
#

# =============================================================================
# Tools
# =============================================================================
GHDL       := ghdl
GHDL_FLAGS := --std=08
GTKWAVE    := gtkwave

# =============================================================================
# Project Root & Directories
# =============================================================================
ROOT       := $(shell pwd)

# RTL sources
RTL_DIR    := src/rtl
TB_DIR     := src/tb

# Common modules (git submodule)
COMMON     := common/modules
FIFO_SRC   := $(COMMON)/fifo/src
UART_SRC   := $(COMMON)/uart/src
NPC_SRC    := $(COMMON)/npc_modulator/src
BILSOLVER  := $(COMMON)/bilinear_solver/src
CLARKE_SRC := $(COMMON)/clarke_transform/src
EDGE_SRC   := $(COMMON)/edge_detector/src

# Build directory (keeps work-obj files out of root)
BUILD_DIR  := build
WORK_DIR   := $(BUILD_DIR)/work

# =============================================================================
# Common Module Sources (order matters for GHDL analysis)
# =============================================================================

# -- Packages (must be analyzed first)
SRC_PKGS := \
	$(BILSOLVER)/BilinearSolverPkg.vhd

# -- Primitives / leaf modules
SRC_PRIMITIVES := \
	$(BILSOLVER)/BilienarSolverUnit_DSP.vhd \
	$(FIFO_SRC)/fifo.vhd \
	$(UART_SRC)/UartTX.vhd \
	$(UART_SRC)/UartRX.vhd \
	$(EDGE_SRC)/EdgeDetector.vhd \
	$(CLARKE_SRC)/ClarkeTransform.vhd

# -- Mid-level modules
SRC_MID := \
	$(UART_SRC)/UartFull.vhd \
	$(BILSOLVER)/BilinearSolverUnit.vhd \
	$(BILSOLVER)/BilinearSolverHandler.vhd \
	$(NPC_SRC)/NPCModulator.vhd \
	$(NPC_SRC)/NPCGateDriver.vhd \
	$(NPC_SRC)/NPCManager.vhd

# =============================================================================
# Project RTL Sources
# =============================================================================
SRC_RTL := \
	$(RTL_DIR)/SerialManager.vhd \
	$(RTL_DIR)/TIM_Solver.vhd \
	$(RTL_DIR)/Top_HIL.vhd

# All sources in dependency order
SRC_ALL := $(SRC_PKGS) $(SRC_PRIMITIVES) $(SRC_MID) $(SRC_RTL)

# =============================================================================
# Testbenches
# =============================================================================
TB_SERIAL  := $(TB_DIR)/tb_SerialManager.vhd
TB_TIM     := $(TB_DIR)/tb_TIMSolver.vhd
TB_TOP     := $(TB_DIR)/tb_TopHIL.vhd

TB_ALL     := $(TB_SERIAL) $(TB_TIM) $(TB_TOP)

# Entity names
ENTITY_SERIAL := tb_SerialManager
ENTITY_TIM    := tb_TIMSolver
ENTITY_TOP    := tb_TopHIL

# =============================================================================
# Waveform files
# =============================================================================
WAVE_DIR       := $(BUILD_DIR)/waves
WAVE_SERIAL    := $(WAVE_DIR)/waves_serial_manager.ghw
WAVE_TIM       := $(WAVE_DIR)/waves_tim_solver.ghw
WAVE_TOP       := $(WAVE_DIR)/waves_top_hil.ghw

# =============================================================================
# Simulation times
# =============================================================================
SIM_TIME_SERIAL := 50ms
SIM_TIME_TIM    := 10ms
SIM_TIME_TOP    := 20ms

# =============================================================================
# GHDL work-dir flag
# =============================================================================
GHDL_WORK := --workdir=$(WORK_DIR)

# =============================================================================
# Default target
# =============================================================================
.PHONY: all
all: sim-serial

# =============================================================================
# Directory creation
# =============================================================================
$(WORK_DIR):
	@mkdir -p $(WORK_DIR)

$(WAVE_DIR):
	@mkdir -p $(WAVE_DIR)

# =============================================================================
# Compile — Analyze all VHDL sources
# =============================================================================
.PHONY: compile
compile: $(WORK_DIR)
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║          Compiling VHDL Sources              ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@echo "── Packages ──"
	@$(GHDL) analyze $(GHDL_FLAGS) $(GHDL_WORK) $(SRC_PKGS)
	@echo "   ✔ Packages analyzed"
	@echo "── Primitives ──"
	@$(GHDL) analyze $(GHDL_FLAGS) $(GHDL_WORK) $(SRC_PRIMITIVES)
	@echo "   ✔ Primitives analyzed"
	@echo "── Mid-level modules ──"
	@$(GHDL) analyze $(GHDL_FLAGS) $(GHDL_WORK) $(SRC_MID)
	@echo "   ✔ Mid-level modules analyzed"
	@echo "── Project RTL ──"
	@$(GHDL) analyze $(GHDL_FLAGS) $(GHDL_WORK) $(SRC_RTL)
	@echo "   ✔ Project RTL analyzed"
	@echo "── Testbenches ──"
	@$(GHDL) analyze $(GHDL_FLAGS) $(GHDL_WORK) $(TB_ALL)
	@echo "   ✔ Testbenches analyzed"
	@echo ""
	@echo "=== Compilation successful ==="
	@echo ""

# =============================================================================
# Elaborate targets
# =============================================================================
.PHONY: elab-serial elab-tim elab-top

elab-serial: compile
	@$(GHDL) elaborate $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_SERIAL)

elab-tim: compile
	@$(GHDL) elaborate $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_TIM)

elab-top: compile
	@$(GHDL) elaborate $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_TOP)

# =============================================================================
# Simulate: SerialManager
# =============================================================================
.PHONY: sim-serial
sim-serial: elab-serial $(WAVE_DIR)
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     Running: tb_SerialManager ($(SIM_TIME_SERIAL))        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@$(GHDL) run $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_SERIAL) \
		--wave=$(WAVE_SERIAL) \
		--stop-time=$(SIM_TIME_SERIAL) 2>&1 | \
		grep -E "(PASS|FAIL|TEST|report|error|assertion)" || true
	@echo ""
	@echo "=== Waveform: $(WAVE_SERIAL) ==="
	@echo ""

# =============================================================================
# Simulate: TIM Solver
# =============================================================================
.PHONY: sim-tim
sim-tim: elab-tim $(WAVE_DIR)
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     Running: tb_TIMSolver ($(SIM_TIME_TIM))          ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@$(GHDL) run $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_TIM) \
		--wave=$(WAVE_TIM) \
		--stop-time=$(SIM_TIME_TIM) 2>&1 | \
		grep -E "(PASS|FAIL|TEST|report|error|assertion)" || true
	@echo ""
	@echo "=== Waveform: $(WAVE_TIM) ==="
	@echo ""

# =============================================================================
# Simulate: Top HIL
# =============================================================================
.PHONY: sim-top
sim-top: elab-top $(WAVE_DIR)
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║     Running: tb_TopHIL ($(SIM_TIME_TOP))            ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@$(GHDL) run $(GHDL_FLAGS) $(GHDL_WORK) $(ENTITY_TOP) \
		--wave=$(WAVE_TOP) \
		--stop-time=$(SIM_TIME_TOP) 2>&1 | \
		grep -E "(PASS|FAIL|TEST|report|error|assertion)" || true
	@echo ""
	@echo "=== Waveform: $(WAVE_TOP) ==="
	@echo ""

# =============================================================================
# Run ALL simulations
# =============================================================================
.PHONY: sim-all
sim-all: sim-serial sim-tim sim-top
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║          All simulations complete            ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""

# =============================================================================
# cocotb (Python) Testbenches
# =============================================================================
COCOTB_DIR := verification/cocotb
TESTCASE   ?=

.PHONY: cocotb cocotb-waves cocotb-setup cocotb-clean

cocotb:
	@$(MAKE) -C $(COCOTB_DIR) test TESTCASE=$(TESTCASE)

cocotb-waves:
	@$(MAKE) -C $(COCOTB_DIR) waves TESTCASE=$(TESTCASE)

cocotb-setup:
	@$(MAKE) -C $(COCOTB_DIR) setup

cocotb-clean:
	@$(MAKE) -C $(COCOTB_DIR) clean

# =============================================================================
# GTKWave targets
# =============================================================================
.PHONY: wave-serial wave-tim wave-top

wave-serial: sim-serial
	@echo "Opening GTKWave: $(WAVE_SERIAL)"
	@$(GTKWAVE) $(WAVE_SERIAL) &

wave-tim: sim-tim
	@echo "Opening GTKWave: $(WAVE_TIM)"
	@$(GTKWAVE) $(WAVE_TIM) &

wave-top: sim-top
	@echo "Opening GTKWave: $(WAVE_TOP)"
	@$(GTKWAVE) $(WAVE_TOP) &

# =============================================================================
# Clean
# =============================================================================
.PHONY: clean
clean: cocotb-clean
	@echo "Cleaning build artifacts..."
	@rm -rf $(BUILD_DIR)
	@rm -f *.cf *.o
	@rm -f src/tb/waves_*.ghw
	@echo "Done."

# =============================================================================
# Help
# =============================================================================
.PHONY: help
help:
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║           HIL Project — Makefile Targets                ║"
	@echo "╠══════════════════════════════════════════════════════════╣"
	@echo "║                                                         ║"
	@echo "║  VHDL Simulation (GHDL):                                ║"
	@echo "║    make sim-serial    SerialManager testbench           ║"
	@echo "║    make sim-tim       TIM Solver testbench              ║"
	@echo "║    make sim-top       Top_HIL testbench                 ║"
	@echo "║    make sim-all       Run all VHDL testbenches          ║"
	@echo "║                                                         ║"
	@echo "║  Waveforms (GTKWave):                                   ║"
	@echo "║    make wave-serial   SerialManager + GTKWave           ║"
	@echo "║    make wave-tim      TIM Solver + GTKWave              ║"
	@echo "║    make wave-top      Top_HIL + GTKWave                 ║"
	@echo "║                                                         ║"
	@echo "║  cocotb (Python) Tests:                                 ║"
	@echo "║    make cocotb        Run all cocotb tests              ║"
	@echo "║    make cocotb TESTCASE=<name>  Run a single test       ║"
	@echo "║    make cocotb-waves  Run cocotb + waveform dump        ║"
	@echo "║    make cocotb-setup  Install Python dependencies       ║"
	@echo "║                                                         ║"
	@echo "║  Build:                                                 ║"
	@echo "║    make compile       Analyze all VHDL sources          ║"
	@echo "║    make clean         Remove all build artifacts        ║"
	@echo "║    make help          Show this message                 ║"
	@echo "║                                                         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
