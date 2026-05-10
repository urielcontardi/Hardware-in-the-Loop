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
PETALINUX_IMAGES := $(PETALINUX_DIR)/images/linux
# XSA from Vivado synthesis — used for BOTH FSBL and bitstream.
# The Vivado 2025.1 XSA has the correct DDR PHY calibration (0x44E458D3)
# that boots this specific EBAZ4205 board. The April-12 "original" XSA
# has a different DDR calibration (0x452464D3) that does NOT boot this board.
XSA_NEW          := $(SYN_HIL)/ebaz4205.xsa
VIVADO_BIT       := $(SYN_HIL)/ebaz4205/ebaz4205.runs/impl_1/ebaz4205_wrapper.bit
# .bin = byte-swapped bitstream required by PetaLinux fpga_manager (fpgautil -b)
# The Vivado .bit has a header that fpga_manager rejects; bootgen strips/swaps it.
VIVADO_BIN       := $(VIVADO_BIT).bin

.PHONY: linux-config linux-build linux-package linux-all linux-all-axi \
        linux-update-sdimages linux-flash linux-extract-fsbl \
        bit-to-bin \
        ps-build ps-build-test ps-deploy ps-deploy-test ps-clean ps-sdk

_petalinux_check_env:
	@if [ ! -f "$(PETALINUX_ENV)" ]; then \
		echo "ERROR: PetaLinux environment not found at $(PETALINUX_ENV)"; \
		exit 1; \
	fi

## Update hardware description from the Vivado 2025.1 XSA
#
# Uses ebaz4205.xsa (generated by Vivado synth) for FSBL — this XSA has the
# DDR PHY calibration (0x44E458D3) that boots this board correctly.
#
# Fixes applied automatically:
#   - ps7_nand_0 → nfc0 rename in system-conf.dtsi (required since PetaLinux 2024.2)
linux-config: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║   PetaLinux — Configure (Vivado 2025.1 XSA) ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(XSA_NEW)" ]; then \
		echo "ERROR: $(XSA_NEW) not found — run 'make synth' first."; \
		exit 1; \
	fi
	@sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 2>/dev/null || true
	@sudo sysctl -w kernel.unprivileged_userns_clone=1 2>/dev/null || true
	@echo "  Usando XSA do Vivado 2025.1 (DDR calibração correta para esta placa)..."
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-config --get-hw-description $(ROOT)/$(XSA_NEW) --silentconfig"
	@echo "  Aplicando fix ps7_nand_0 → nfc0 no device tree..."
	@DTSI=$(PETALINUX_DIR)/components/plnx_workspace/device-tree/device-tree/system-conf.dtsi; \
	if [ -f "$$DTSI" ] && grep -q 'ps7_nand_0' "$$DTSI"; then \
		sed -i 's/&ps7_nand_0/\&nfc0/g' "$$DTSI"; \
		echo "  ✓ ps7_nand_0 → nfc0"; \
		bash -c "source $(PETALINUX_ENV) && cd $(PETALINUX_DIR) && \
			bitbake -c cleansstate device-tree 2>/dev/null || true"; \
	fi
	@echo "  ✓ Configuração concluída."

## Build kernel + rootfs + FSBL (from Vivado 2025.1 XSA — correct DDR calibration)
linux-build: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║        PetaLinux — Build (kernel+rootfs)     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 2>/dev/null || true
	@sudo sysctl -w kernel.unprivileged_userns_clone=1 2>/dev/null || true
	@DTSI=$(PETALINUX_DIR)/components/plnx_workspace/device-tree/device-tree/system-conf.dtsi; \
	if [ -f "$$DTSI" ] && grep -q 'ps7_nand_0' "$$DTSI"; then \
		sed -i 's/&ps7_nand_0/\&nfc0/g' "$$DTSI"; \
		echo "  ✓ ps7_nand_0 → nfc0 (safety check)"; \
		bash -c "source $(PETALINUX_ENV) && cd $(PETALINUX_DIR) && \
			bitbake -c cleansstate device-tree 2>/dev/null || true"; \
	fi
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-build"

## Package BOOT.BIN:
#   FSBL      = images/linux/zynq_fsbl.elf  (from Vivado 2025.1 XSA — DDR 0x44E458D3)
#   Bitstream = ebaz4205_wrapper.bit (DSP48E1, EMIO Ethernet, HIL_Regs@0x43C00000)
#   U-Boot    = images/linux/u-boot.elf
#   DTB       = images/linux/system.dtb
linux-package: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║        PetaLinux — Package BOOT.BIN          ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(PETALINUX_IMAGES)/zynq_fsbl.elf" ]; then \
		echo "ERROR: zynq_fsbl.elf not found — run 'make linux-build' first."; \
		exit 1; \
	fi
	@if [ ! -f "$(VIVADO_BIT)" ]; then \
		echo "ERROR: $(VIVADO_BIT) not found — run 'make synth' first."; \
		exit 1; \
	fi
	@echo "  FSBL     : $(PETALINUX_IMAGES)/zynq_fsbl.elf (Vivado 2025.1 XSA, DDR=0x44E458D3)"
	@echo "  Bitstream: $(VIVADO_BIT) (DSP48E1 — new synthesis)"
	@echo "  U-Boot   : $(PETALINUX_IMAGES)/u-boot.elf"
	@echo "  DTB      : $(PETALINUX_IMAGES)/system.dtb"
	@bash -c "source $(PETALINUX_ENV) && \
		cd $(PETALINUX_DIR) && \
		petalinux-package boot --force \
			--fsbl  images/linux/zynq_fsbl.elf \
			--fpga  $(ROOT)/$(VIVADO_BIT) \
			--u-boot"
	@echo ""
	@echo "  ✓ BOOT.BIN gerado em $(PETALINUX_IMAGES)/"

## Full flow: config → build → package
linux-all: linux-config linux-build linux-package

## Copy linux-package output → sd_images/ then flash
linux-update-sdimages:
	@echo "  Copiando $(PETALINUX_IMAGES)/ → $(SYN_HIL)/sd_images/ ..."
	@for f in BOOT.BIN boot.scr image.ub rootfs.tar.gz; do \
		if [ ! -f "$(PETALINUX_IMAGES)/$$f" ]; then \
			echo "ERROR: $$f não encontrado — rode 'make linux-build && make linux-package' primeiro"; \
			exit 1; \
		fi; \
	done
	@cp $(PETALINUX_IMAGES)/BOOT.BIN      $(SYN_HIL)/sd_images/
	@cp $(PETALINUX_IMAGES)/boot.scr      $(SYN_HIL)/sd_images/
	@cp $(PETALINUX_IMAGES)/image.ub      $(SYN_HIL)/sd_images/
	@cp $(PETALINUX_IMAGES)/rootfs.tar.gz $(SYN_HIL)/sd_images/
	@echo "  ✓ sd_images/ atualizado."

## Full flow: Vivado project → synth → linux-all → sd_images → flash
linux-all-axi:
	@echo ""
	@echo "╔═══════════════════════════════════════════════════════════╗"
	@echo "║  Full HIL Rebuild: Vivado → Synth → PetaLinux → SD       ║"
	@echo "╚═══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Step (1/5): Creating Vivado project..."
	@$(MAKE) vivado-project
	@echo ""
	@echo "Step (2/5): Synthesis + Implementation + XSA..."
	@$(MAKE) synth
	@echo ""
	@echo "Step (3/5): PetaLinux config (Vivado 2025.1 XSA → FSBL + device tree)..."
	@$(MAKE) linux-config
	@echo ""
	@echo "Step (4/5): Build kernel + rootfs + FSBL..."
	@$(MAKE) linux-build
	@echo ""
	@echo "Step (5/5): Package BOOT.BIN (new bitstream) + update sd_images..."
	@$(MAKE) linux-package linux-update-sdimages
	@echo ""
	@echo "✅ Full rebuild complete!"
	@echo "  Images ready in: $(SYN_HIL)/sd_images/"
	@echo ""
	@echo "  Next: make linux-flash SD=/dev/sdX"

## Flash SD card (usage: make linux-flash SD=/dev/sdX)
# flash_sd.sh uses sd_images/ by default (set SD_IMAGES_DIR env to override).
# After make linux-package, run: make linux-update-sdimages && make linux-flash SD=...
linux-flash:
	@if [ "$(SD)" = "/dev/sdX" ]; then \
		echo "ERROR: specify SD device — example: make linux-flash SD=/dev/sda"; \
		exit 1; \
	fi
	@sudo $(SYN_HIL)/flash_sd.sh $(SD)

# =============================================================================
# PS Application (src/ps_app)
# =============================================================================
PS_APP_DIR   := src/ps_app
PS_SDK_ENV   := $(PETALINUX_DIR)/images/linux/sdk/environment-setup-cortexa9t2hf-neon-amd-linux-gnueabi
IP           ?= 192.168.1.100
BOARD_USER   ?= petalinux
BOARD_HOME   ?= /home/$(BOARD_USER)

.PHONY: ps-build ps-build-test ps-deploy ps-deploy-test ps-deploy-bit hil-deploy-test ps-clean ps-sdk

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

## Cross-compile FPGA smoke test binary
ps-build-test:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PS App — Build test_fpga (ARM)         ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(PS_SDK_ENV)" ]; then \
		echo "ERROR: SDK not found. Run 'make ps-sdk' first."; \
		exit 1; \
	fi
	@bash -c "source $(PS_SDK_ENV) && \
		$(MAKE) -C $(PS_APP_DIR) test"
	@echo "  Binary: $(PS_APP_DIR)/test_fpga"

## Deploy PS application to board via SCP
ps-deploy: ps-build
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PS App — Deploy to board               ║"
	@echo "╚══════════════════════════════════════════════╝"
	@$(MAKE) -C $(PS_APP_DIR) deploy IP=$(IP)

## Deploy smoke test to board via SCP
ps-deploy-test: ps-build-test
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       PS App — Deploy test_fpga to board     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@$(MAKE) -C $(PS_APP_DIR) deploy-test IP=$(IP)

## Convert Vivado .bit to byte-swapped .bin required by PetaLinux fpga_manager
# PetaLinux 2024+ rejects the raw .bit header; fpgautil -b needs .bin format.
# bootgen strips the Vivado header and byte-swaps the payload automatically.
bit-to-bin: _petalinux_check_env
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       Vivado .bit → .bin (bootgen)           ║"
	@echo "╚══════════════════════════════════════════════╝"
	@if [ ! -f "$(VIVADO_BIT)" ]; then \
		echo "ERROR: $(VIVADO_BIT) not found — run 'make synth' first."; \
		exit 1; \
	fi
	$(eval _BIF := $(shell mktemp /tmp/bit2bin.XXXXXX.bif))
	@printf 'all:\n{\n    %s\n}\n' "$(ROOT)/$(VIVADO_BIT)" > $(_BIF)
	@bash -c "source $(PETALINUX_ENV) && \
		bootgen -image $(_BIF) -arch zynq -process_bitstream bin -w on \
		        -o $(ROOT)/$(VIVADO_BIN)"
	@rm -f $(_BIF)
	@echo "  .bin gerado: $(VIVADO_BIN)"
	@sha256sum "$(VIVADO_BIN)"

## Deploy the current Vivado bitstream (.bin) to board via SCP
ps-deploy-bit: bit-to-bin
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       Vivado — Deploy bitstream to board     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@sha256sum "$(VIVADO_BIN)"
	scp "$(VIVADO_BIN)" $(BOARD_USER)@$(IP):$(BOARD_HOME)/ebaz4205_wrapper.bin
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/ebaz4205_wrapper.bin"
	@echo "Load on board: sudo fpgautil -b $(BOARD_HOME)/ebaz4205_wrapper.bin"

## Deploy bitstream + smoke test from this workspace to board via SCP
hil-deploy-test: ps-build-test ps-deploy-bit
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       HIL — Deploy bitstream + test_fpga     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@sha256sum "$(PS_APP_DIR)/test_fpga"
	scp "$(PS_APP_DIR)/test_fpga" $(BOARD_USER)@$(IP):$(BOARD_HOME)/
	@echo "Run on board:"
	@echo "  sudo fpgautil -b $(BOARD_HOME)/ebaz4205_wrapper.bin"
	@echo "  sudo $(BOARD_HOME)/test_fpga"

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
# HIL Monitor (Wails/Go) Targets
# =============================================================================
HIL_GO_DIR := apps/hil-go
HIL_GO_OUT := $(BUILD_DIR)/hil-monitor

# Resolve wails and go binaries
WAILS := $(shell command -v wails 2>/dev/null || echo $(HOME)/go/bin/wails)
GO    := $(shell command -v go 2>/dev/null \
	|| ls /usr/local/go/bin/go 2>/dev/null \
	|| ls $(HOME)/go/bin/go   2>/dev/null)
ifeq ($(GO),)
GO := go
endif

.PHONY: hil-go-linux hil-go-darwin hil-go-dev hil-go-all hil-go-clean

## Build native app for Linux x86-64
hil-go-linux:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       HIL Monitor — Linux x86-64 (Wails)    ║"
	@echo "╚══════════════════════════════════════════════╝"
	@mkdir -p $(HIL_GO_OUT)
	@cd $(HIL_GO_DIR) && PATH="$$PATH:/usr/local/go/bin:$(HOME)/go/bin" \
		$(WAILS) build -platform linux/amd64 -tags webkit2_41
	@mkdir -p $(HIL_GO_OUT)
	@cp $(HIL_GO_DIR)/build/bin/hil-monitor $(HIL_GO_OUT)/hil-monitor-linux-amd64
	@echo "  Binary → $(HIL_GO_OUT)/hil-monitor-linux-amd64"

## Build native app for macOS ARM64 — must run on macOS
hil-go-darwin:
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║       HIL Monitor — macOS ARM64 (Wails)     ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo "  NOTE: cross-compile macOS→Linux not supported by Wails."
	@echo "        Run this target on a Mac with Wails installed."
	@mkdir -p $(HIL_GO_OUT)
	@cd $(HIL_GO_DIR) && PATH="$$PATH:/usr/local/go/bin:$(HOME)/go/bin" \
		$(WAILS) build -platform darwin/arm64
	@mkdir -p $(HIL_GO_OUT)
	@cp $(HIL_GO_DIR)/build/bin/hil-monitor $(HIL_GO_OUT)/hil-monitor-darwin-arm64
	@echo "  Binary → $(HIL_GO_OUT)/hil-monitor-darwin-arm64"

## Build for both platforms (macOS target requires macOS host)
hil-go-all: hil-go-linux hil-go-darwin

## Start dev mode (hot-reload window)
hil-go-dev:
	@echo "Starting Wails dev mode..."
	@cd $(HIL_GO_DIR) && PATH="$$PATH:/usr/local/go/bin:$(HOME)/go/bin" \
		$(WAILS) dev

## Remove Wails build artifacts
hil-go-clean:
	@rm -rf $(HIL_GO_OUT) $(HIL_GO_DIR)/frontend/dist $(HIL_GO_DIR)/frontend/wailsjs
	@echo "  Cleaned $(HIL_GO_OUT)"


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
	@echo "║  HIL Monitor (Wails/Go):                                ║"
	@echo "║    make hil-go-linux   Build native app Linux x86-64   ║"
	@echo "║    make hil-go-darwin  Build native app macOS ARM64    ║"
	@echo "║    make hil-go-dev     Start Wails dev mode            ║"
	@echo "║    make hil-go-all     Build for all targets           ║"
	@echo "║    make hil-go-clean   Remove build artifacts          ║"
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
