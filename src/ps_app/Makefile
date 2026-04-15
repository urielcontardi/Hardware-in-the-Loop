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

TARGET  := hil_controller
SRCS    := main.c gpio.c vf_ctrl.c
CFLAGS  := -O2 -Wall -Wextra
LDFLAGS := -lm -lpthread -lrt

# Cross-compiler (set by PetaLinux SDK environment-setup script)
# If CC is not set to the cross-compiler, fallback with a warning
ifeq ($(origin CC), default)
    $(warning CC not set — run: source <sdk>/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi)
    CC := arm-linux-gnueabihf-gcc
endif

.PHONY: all native clean deploy

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "Built: $@ ($(shell file $@ | grep -o 'ARM\|x86[^ ]*'))"

native:
	gcc $(CFLAGS) -DNATIVE_BUILD -o $(TARGET)_native $(SRCS) $(LDFLAGS)
	@echo "Built native: $(TARGET)_native"

clean:
	rm -f $(TARGET) $(TARGET)_native

deploy: $(TARGET)
	@if [ -z "$(IP)" ]; then echo "Usage: make deploy IP=<ip>"; exit 1; fi
	scp $(TARGET) root@$(IP):/home/root/
	@echo "Deployed to root@$(IP):/home/root/$(TARGET)"
