# =============================================================================
# Makefile — HIL PS Application
#
# Cross-compilação para ARM Cortex-A9 (EBAZ4205 / Zynq-7010)
#
# Uso:
#   make              — cross-compila com toolchain do PetaLinux SDK
#   make native       — compila nativo (para testes no x86, sem hardware)
#   make clean        — remove binários
#   make deploy IP=<ip_da_placa>  — copia para a placa via SCP
#
# Pré-requisito (uma vez):
#   source <petalinux_dir>/images/linux/sdk/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi
# =============================================================================

TARGET      := hil_controller
TARGET_TEST := test_fpga
SRCS        := main.c gpio.c vf_ctrl.c telemetry.c
CFLAGS  := -O2 -Wall -Wextra
LDFLAGS := -lm -lpthread -lrt

# Cross-compiler (set by PetaLinux SDK environment-setup script)
# If CC is not set to the cross-compiler, fallback with a warning
ifeq ($(origin CC), default)
    $(warning CC not set — run: source <sdk>/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi)
    CC := arm-linux-gnueabihf-gcc
endif

.PHONY: all test native clean deploy deploy-test

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

test: $(TARGET_TEST)

$(TARGET_TEST): test_fpga.c gpio.c gpio.h
	$(CC) $(CFLAGS) -o $@ test_fpga.c gpio.c -lm
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

native:
	gcc $(CFLAGS) -DNATIVE_BUILD -o $(TARGET)_native $(SRCS) $(LDFLAGS)
	@echo "Built native: $(TARGET)_native"

clean:
	rm -f $(TARGET) $(TARGET)_native $(TARGET_TEST)

BOARD_USER ?= petalinux
BOARD_HOME  = /home/$(BOARD_USER)

deploy: $(TARGET)
	@if [ -z "$(IP)" ]; then echo "Usage: make deploy IP=<ip>"; exit 1; fi
	scp $(TARGET) $(BOARD_USER)@$(IP):$(BOARD_HOME)/
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/$(TARGET)"
	@echo "Run on board: sudo $(BOARD_HOME)/$(TARGET)"

deploy-test: $(TARGET_TEST)
	@if [ -z "$(IP)" ]; then echo "Usage: make deploy-test IP=<ip>"; exit 1; fi
	scp $(TARGET_TEST) $(BOARD_USER)@$(IP):$(BOARD_HOME)/
	@echo "Deployed to $(BOARD_USER)@$(IP):$(BOARD_HOME)/$(TARGET_TEST)"
	@echo "Run on board: sudo $(BOARD_HOME)/$(TARGET_TEST)"
