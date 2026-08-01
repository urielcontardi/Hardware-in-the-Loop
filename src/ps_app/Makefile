# =============================================================================
# Makefile — HIL PS Application
#
# Cross-compilation for ARM Cortex-A9 (EBAZ4205 / Zynq-7010)
#
# Usage:
#   make              — cross-compile with the PetaLinux SDK toolchain
#   make native       — build natively for x86 tests without hardware
#   make clean        — remove binaries
#   make deploy IP=<board_ip>  — copy binaries to the board over SCP
#
# One-time prerequisite:
#   source <petalinux_dir>/images/linux/sdk/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi
# =============================================================================

TARGET      := hil_controller
TARGET_TEST := test_fpga
TARGET_SUP  := hil_supervisor
SRCS        := main.c gpio.c vf_ctrl.c vf_irq.c telemetry.c dma_telem.c pwm_events.c
SUP_SRCS    := supervisor.c
CFLAGS  := -O2 -Wall -Wextra
PS_VERSION ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || printf unknown)
CFLAGS  += -DPS_VERSION=\"$(PS_VERSION)\"
LDFLAGS := -lm -lpthread -lrt

# Cross-compiler (set by PetaLinux SDK environment-setup script)
# If CC is not set to the cross-compiler, fallback with a warning
ifeq ($(origin CC), default)
ifneq ($(filter native clean,$(MAKECMDGOALS)),)
    CC := gcc
else
    $(warning CC not set - source the PetaLinux SDK environment)
    CC := arm-linux-gnueabihf-gcc
endif
endif

.PHONY: all test native clean deploy deploy-test

all: $(TARGET) $(TARGET_SUP)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

$(TARGET_SUP): $(SUP_SRCS)
	$(CC) $(CFLAGS) -o $@ $^
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

test: $(TARGET_TEST)

$(TARGET_TEST): test_fpga.c gpio.c gpio.h
	$(CC) $(CFLAGS) -o $@ test_fpga.c gpio.c -lm
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

native:
	gcc $(CFLAGS) -DNATIVE_BUILD -o $(TARGET)_native $(SRCS) $(LDFLAGS)
	gcc $(CFLAGS) -DNATIVE_BUILD -o $(TARGET_SUP)_native $(SUP_SRCS)
	@echo "Built native: $(TARGET)_native"
	@echo "Built native: $(TARGET_SUP)_native"

clean:
	rm -f $(TARGET) $(TARGET)_native $(TARGET_SUP) $(TARGET_SUP)_native $(TARGET_TEST)

BOARD_USER ?= petalinux
BOARD_HOME  = /home/$(BOARD_USER)

deploy: $(TARGET) $(TARGET_SUP)
	@if [ -z "$(IP)" ]; then echo "Usage: make deploy IP=<ip>"; exit 1; fi
	scp $(TARGET) $(TARGET_SUP) $(BOARD_USER)@$(IP):$(BOARD_HOME)/
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/$(TARGET)"
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/$(TARGET_SUP)"
	@echo "Run on board: sudo $(BOARD_HOME)/$(TARGET)"

deploy-test: $(TARGET_TEST)
	@if [ -z "$(IP)" ]; then echo "Usage: make deploy-test IP=<ip>"; exit 1; fi
	scp $(TARGET_TEST) $(BOARD_USER)@$(IP):$(BOARD_HOME)/
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/$(TARGET_TEST)"
	@echo "Run on board: sudo $(BOARD_HOME)/$(TARGET_TEST)"
