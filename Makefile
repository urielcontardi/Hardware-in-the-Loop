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
#   make linux-config       - Update PetaLinux hardware description from XSA
#   make linux-build        - Build PetaLinux kernel + rootfs
#   make linux-package      - Package BOOT.bin + image.ub
#   make linux-all          - Full PetaLinux flow (config → build → package)
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
# Vivado / Synthesis targets
# =============================================================================
VIVADO      := /opt/Xilinx/2025.1/Vivado/bin/vivado
SYN_HIL     := syn/hil
VIVADO_PROJ := $(SYN_HIL)/ebaz4205/ebaz4205.xpr
NVC         := nvc
NVC_FLAGS   := --std=2008
SD          ?= /dev/sdX

.PHONY: vivado-project sim-dsp-compare sim-bsu-compare sim-clarke synth flash

## Create the Vivado project from TCL (syn/hil/create_ebaz4205_project.tcl)
vivado-project:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║      Creating Vivado ebaz4205 project        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@cd $(SYN_HIL) && $(VIVADO) -mode batch \
		-source create_ebaz4205_project.tcl \
		-log vivado_create.log \
		-journal vivado_create.jou
	@echo "Project: $(VIVADO_PROJ)"

## Stub vs IP direct comparison — both architectures side-by-side (requires vivado-project first)
sim-dsp-compare:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  DSP Stub vs IP — Side-by-Side (xsim)        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(VIVADO_PROJ)" ]; then \
		echo "ERROR: project not found — run 'make vivado-project' first"; \
		exit 1; \
	fi
	@$(VIVADO) -mode batch \
		-source $(SYN_HIL)/run_sim_dsp_compare.tcl \
		-log $(SYN_HIL)/vivado_sim_compare.log \
		-journal $(SYN_HIL)/vivado_sim_compare.jou
	@echo ""
	@echo "Results → $(SYN_HIL)/vivado_sim_compare.log"
	@grep -E "MATCH|MISMATCH|PASS|FAIL|ERROR|ALL VECTORS" $(SYN_HIL)/vivado_sim_compare.log || true

## BilinearSolverUnit stub vs IP full-solver comparison (requires vivado-project first)
sim-bsu-compare:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  BSU Stub vs IP — Full Solver (xsim)         ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(VIVADO_PROJ)" ]; then \
		echo "ERROR: project not found — run 'make vivado-project' first"; \
		exit 1; \
	fi
	@$(VIVADO) -mode batch \
		-source $(SYN_HIL)/run_sim_bsu_compare.tcl \
		-log $(SYN_HIL)/vivado_bsu_compare.log \
		-journal $(SYN_HIL)/vivado_bsu_compare.jou
	@echo ""
	@echo "Results → $(SYN_HIL)/vivado_bsu_compare.log"
	@grep -E "PASS|FAIL|MISMATCH|ALL TESTS" $(SYN_HIL)/vivado_bsu_compare.log || true

## Clarke transform behavioral simulation — exports VCD for GTKWave
sim-clarke:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  Clarke Transform — Behavioral (xsim)        ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(VIVADO_PROJ)" ]; then \
		echo "ERROR: project not found — run 'make vivado-project' first"; \
		exit 1; \
	fi
	@cd $(SYN_HIL) && $(VIVADO) -mode batch \
		-source run_sim_clarke.tcl \
		-log vivado_clarke.log \
		-journal vivado_clarke.jou
	@echo ""
	@echo "Results → $(SYN_HIL)/vivado_clarke.log"
	@grep -E "PASS|FAIL|ERROR|Waveform ready" $(SYN_HIL)/vivado_clarke.log || true

## Synthesize + implement + export XSA (requires vivado-project first)
synth:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  Synthesis + Implementation + XSA Export     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(VIVADO_PROJ)" ]; then \
		echo "ERROR: project not found — run 'make vivado-project' first"; \
		exit 1; \
	fi
	@cd $(SYN_HIL) && $(VIVADO) -mode batch \
		-source run_impl_export.tcl \
		-log vivado_impl.log \
		-journal vivado_impl.jou
	@echo ""
	@grep -E "XSA exportado|ERROR|WARNING.*critical" $(SYN_HIL)/vivado_impl.log || true

## Flash SD card with pre-built images (usage: make flash SD=/dev/sdX)
flash:
	@if [ "$(SD)" = "/dev/sdX" ]; then \
		echo "ERROR: specify SD device — example: make flash SD=/dev/sda"; \
		exit 1; \
	fi
	@sudo $(SYN_HIL)/flash_sd.sh $(SD)

# =============================================================================
# PetaLinux targets
# =============================================================================
PETALINUX_DIR    := $(SYN_HIL)/ebaz4205_petalinux
PETALINUX_ENV    := $(HOME)/xilinx/petalinux/settings.sh
XSA_FILE         := $(SYN_HIL)/ebaz4205.xsa
PETALINUX_IMAGES := $(PETALINUX_DIR)/images/linux

.PHONY: linux-config linux-build linux-package linux-all linux-flash linux-clean ps-build ps-deploy ps-clean ps-sdk

_petalinux_check_env:
	@if [ ! -f "$(PETALINUX_ENV)" ]; then \
		echo "ERROR: PetaLinux environment not found at $(PETALINUX_ENV)"; \
		exit 1; \
	fi

_petalinux_check_xsa:
	@if [ ! -f "$(XSA_FILE)" ]; then \
		echo "ERROR: $(XSA_FILE) not found — run 'make synth' first"; \
		exit 1; \
	fi

## Update hardware description from XSA (run after make synth)
linux-config: _petalinux_check_env _petalinux_check_xsa
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║   PetaLinux — Update HW description (XSA)   ║"
	@echo "╚══════════════════════════════════════════════╝"
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-config --get-hw-description ../ebaz4205.xsa --silentconfig"
	@# Remove ps7_nand_0 block — not present in EBAZ4205 XSA, causes dtc error
	@DTSI=$(PETALINUX_DIR)/components/plnx_workspace/device-tree/device-tree/system-conf.dtsi; \
	if grep -q 'ps7_nand_0' "$$DTSI"; then \
		python3 -c "\
import re, sys; \
txt = open('$$DTSI').read(); \
txt = re.sub(r'&ps7_nand_0 \{[^}]*\{[^}]*\}[^}]*\{[^}]*\}[^}]*\{[^}]*\}[^}]*\};', \
            '/* ps7_nand_0 removed — label not present in current XSA; boot via SD */', txt, flags=re.DOTALL); \
open('$$DTSI','w').write(txt)"; \
		echo "  Removed ps7_nand_0 block from system-conf.dtsi"; \
	fi
	@echo "  HW description updated."

## Build kernel + rootfs
linux-build: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║        PetaLinux — Build (kernel+rootfs)     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-build"

## Package BOOT.bin + image.ub
linux-package: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║        PetaLinux — Package BOOT.bin          ║"
	@echo "╚══════════════════════════════════════════════╝"
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-package boot --force \
			--fsbl images/linux/zynq_fsbl.elf \
			--fpga images/linux/system.bit \
			--u-boot"
	@echo ""
	@echo "  Boot files em: $(PETALINUX_IMAGES)/"
	@echo "  Copiar para SD (partição boot): BOOT.bin boot.scr image.ub system.dtb"

## Full flow: config → build → package
linux-all: linux-config linux-build linux-package

## Copy boot files to SD card boot partition (usage: make linux-flash SD=/dev/sdX)
linux-flash:
	@if [ "$(SD)" = "/dev/sdX" ]; then \
		echo "ERROR: specify SD device — example: make linux-flash SD=/dev/sda"; \
		exit 1; \
	fi
	@BOOT_PART=$$(lsblk -lno NAME,TYPE $(SD) | awk '$$2=="part"{print "/dev/"$$1}' | head -1); \
	ROOTFS_PART=$$(lsblk -lno NAME,TYPE $(SD) | awk '$$2=="part"{print "/dev/"$$1}' | sed -n '2p'); \
	MOUNT_BOOT=$$(mktemp -d); \
	MOUNT_ROOTFS=$$(mktemp -d); \
	echo "Boot partition:  $$BOOT_PART → $$MOUNT_BOOT"; \
	echo "Rootfs partition: $$ROOTFS_PART → $$MOUNT_ROOTFS"; \
	sudo mount $$BOOT_PART $$MOUNT_BOOT && \
	sudo cp $(PETALINUX_IMAGES)/BOOT.BIN \
	        $(PETALINUX_IMAGES)/image.ub \
	        $(PETALINUX_IMAGES)/boot.scr \
	        $(PETALINUX_IMAGES)/system.dtb \
	        $$MOUNT_BOOT/ && \
	echo "  Boot files copied." && \
	sudo umount $$MOUNT_BOOT && \
	sudo mount $$ROOTFS_PART $$MOUNT_ROOTFS && \
	sudo tar xf $(PETALINUX_IMAGES)/rootfs.tar.gz -C $$MOUNT_ROOTFS/ && \
	echo "  Rootfs extracted." && \
	sudo umount $$MOUNT_ROOTFS && \
	rmdir $$MOUNT_BOOT $$MOUNT_ROOTFS && \
	echo "" && \
	echo "SD card ready. Insert into EBAZ4205 and power on."

# =============================================================================
# PS Application (src/ps_app)
# =============================================================================
PS_APP_DIR   := src/ps_app
PS_SDK_ENV   := $(PETALINUX_DIR)/images/linux/sdk/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi
IP           ?= 192.168.1.100

.PHONY: ps-build ps-deploy ps-clean ps-sdk

## Generate PetaLinux SDK (run once after linux-build)
ps-sdk: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PetaLinux — Generate SDK               ║"
	@echo "╚══════════════════════════════════════════════╝"
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-build --sdk && \
		petalinux-package sysroot"
	@echo "  SDK ready at: $(PS_SDK_ENV)"

## Cross-compile PS application
ps-build:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PS App — Cross-compile (ARM)           ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(PS_SDK_ENV)" ]; then \
		echo "ERROR: SDK not found. Run 'make ps-sdk' first."; \
		exit 1; \
	fi
	@bash -c "source $(PS_SDK_ENV) && \
		$(MAKE) -C $(PS_APP_DIR)"
	@echo "  Binary: $(PS_APP_DIR)/hil_controller"

## Deploy PS application to board via SCP
ps-deploy: ps-build
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PS App — Deploy to board               ║"
	@echo "╚══════════════════════════════════════════════╝"
	@$(MAKE) -C $(PS_APP_DIR) deploy IP=$(IP)

## Clean PS application build
ps-clean:
	@$(MAKE) -C $(PS_APP_DIR) clean

# =============================================================================
# cocotb (Python) Testbenches
# =============================================================================
COCOTB_DIR := verification/cocotb
TESTCASE   ?=
TOP        ?= top_hil
SIM        ?= ghdl
GUI_DIR    := apps/hil-gui-tauri
SHELL      := /bin/bash

.PHONY: cocotb cocotb-waves cocotb-tim-ref cocotb-tim-vf cocotb-tim-vf-bg cocotb-tim-sine cocotb-report cocotb-report-overlay cocotb-report-sine cocotb-setup cocotb-setup-nvc cocotb-clean

cocotb:
	@$(MAKE) -C $(COCOTB_DIR) test SIM=$(SIM) TOP=$(TOP) TESTCASE=$(TESTCASE)

cocotb-waves:
	@$(MAKE) -C $(COCOTB_DIR) waves SIM=$(SIM) TOP=$(TOP) TESTCASE=$(TESTCASE)

cocotb-tim-ref:
	@$(MAKE) -C $(COCOTB_DIR) tim-ref SIM=$(SIM)

cocotb-tim-vf:
	@$(MAKE) -C $(COCOTB_DIR) tim-vf SIM=$(SIM)

cocotb-tim-vf-bg:
	@$(MAKE) -C $(COCOTB_DIR) tim-vf-bg SIM=$(SIM)

cocotb-tim-sine:
	@$(MAKE) -C $(COCOTB_DIR) tim-sine SIM=$(SIM)

cocotb-report:
	@$(MAKE) -C $(COCOTB_DIR) report

cocotb-report-overlay:
	@$(MAKE) -C $(COCOTB_DIR) report-overlay

cocotb-report-sine:
	@$(MAKE) -C $(COCOTB_DIR) report-sine

cocotb-setup:
	@$(MAKE) -C $(COCOTB_DIR) setup

cocotb-setup-nvc:
	@$(MAKE) -C $(COCOTB_DIR) setup-nvc

cocotb-clean:
	@$(MAKE) -C $(COCOTB_DIR) clean

# =============================================================================
# GUI (Tauri) Targets
# =============================================================================
# When invoked from a tty terminal that sits under an active graphical session
# (e.g. VS Code remote, SSH with X forwarding, or a bare TTY in a GNOME session),
# DISPLAY may be empty even though an X server is running.
# _GUI_DISPLAY resolves in order:
#   1. Whatever is already in DISPLAY (normal desktop terminal).
#   2. The display extracted from `who` output, e.g. ":1" from "user :1 (...)".
#   3. Hard-coded fallback ":1".
_GUI_DISPLAY := $(or $(DISPLAY),$(shell who | grep -oP '\(:\d+\)' | tr -d '()' | head -1),:1)
# cargo lives in ~/.cargo/bin which is not always in PATH when make is called from a tty.
_CARGO_ENV   := $${HOME}/.cargo/env

.PHONY: gui-setup gui-check gui-dev gui-build gui-build-linux

gui-setup:
	@echo "Installing GUI dependencies (npm)..."
	@cd $(GUI_DIR) && npm install

gui-check:
	@echo "Checking GUI frontend and backend (DISPLAY=$(_GUI_DISPLAY))..."
	@cd $(GUI_DIR) && DISPLAY=$(_GUI_DISPLAY) npm run frontend:build
	@source $(_CARGO_ENV) && cd $(GUI_DIR)/src-tauri && DISPLAY=$(_GUI_DISPLAY) cargo check

gui-dev:
	@echo "Starting GUI in development mode (DISPLAY=$(_GUI_DISPLAY))..."
	@source $(_CARGO_ENV) && cd $(GUI_DIR) && DISPLAY=$(_GUI_DISPLAY) npm run dev

gui-build:
	@echo "Building GUI (default tauri bundle targets, DISPLAY=$(_GUI_DISPLAY))..."
	@source $(_CARGO_ENV) && cd $(GUI_DIR) && DISPLAY=$(_GUI_DISPLAY) npm run build

gui-build-linux:
	@echo "Building GUI Linux bundles (deb,rpm, DISPLAY=$(_GUI_DISPLAY))..."
	@source $(_CARGO_ENV) && cd $(GUI_DIR) && DISPLAY=$(_GUI_DISPLAY) npm run build:linux

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
	@echo "║    make cocotb TOP=<top> TESTCASE=<name> Run one test   ║"
	@echo "║    make cocotb-tim-ref  TIM_Solver vs C ref (DC)        ║"
	@echo "║    make cocotb-tim-vf      TIM_Solver V/F ramp (foreground) ║"
	@echo "║    make cocotb-tim-vf-bg   TIM_Solver V/F ramp (background) ║"
	@echo "║    make cocotb-tim-sine TIM_Solver vs C ref (60 Hz AC) ║"
	@echo "║    make cocotb-waves    Run cocotb + waveform dump      ║"
	@echo "║    make cocotb-setup  Install Python dependencies       ║"
	@echo "║                                                         ║"
	@echo "║  Desktop GUI (Tauri):                                   ║"
	@echo "║    make gui-setup     Install GUI npm dependencies      ║"
	@echo "║    make gui-check     Frontend build + cargo check      ║"
	@echo "║    make gui-dev       Run GUI dev mode                  ║"
	@echo "║    make gui-build     Full tauri build                  ║"
	@echo "║    make gui-build-linux Build deb/rpm bundles           ║"
	@echo "║                                                         ║"
	@echo "║  Vivado / Synthesis (EBAZ4205):                         ║"
	@echo "║    make vivado-project  Create ebaz4205.xpr             ║"
	@echo "║    make synth           Synth + impl + export XSA       ║"
	@echo "║    make sim-dsp-compare DSP stub vs IP (xsim)           ║"
	@echo "║    make sim-bsu-compare BSU full-solver stub vs IP      ║"
	@echo "║    make sim-clarke      Clarke transform (xsim + VCD)   ║"
	@echo "║    make flash SD=/dev/sdX  Flash SD card                ║"
	@echo "║                                                         ║"
	@echo "║  PetaLinux (EBAZ4205):                                  ║"
	@echo "║    make linux-config    Import XSA into PetaLinux       ║"
	@echo "║    make linux-build     Build kernel + rootfs           ║"
	@echo "║    make linux-package   Package BOOT.bin + image.ub     ║"
	@echo "║    make linux-all       Full flow: config→build→package ║"
	@echo "║    make linux-flash SD=/dev/sdX  Flash SD card          ║"
	@echo "║                                                         ║"
	@echo "║  PS Application (src/ps_app):                           ║"
	@echo "║    make ps-sdk          Generate PetaLinux SDK          ║"
	@echo "║    make ps-build        Cross-compile for ARM           ║"
	@echo "║    make ps-deploy IP=x  Build + SCP to board            ║"
	@echo "║    make ps-clean        Remove PS app binary            ║"
	@echo "║                                                         ║"
	@echo "║  Build:                                                 ║"
	@echo "║    make compile       Analyze all VHDL sources          ║"
	@echo "║    make clean         Remove all build artifacts        ║"
	@echo "║    make help          Show this message                 ║"
	@echo "║                                                         ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
