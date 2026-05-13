#!/bin/bash
# =============================================================================
# build_fresh_axi_design.sh
#
# Build completo do NOVO design (AXI GPIO-based) a partir do zero
#
# Este script:
# 1. Regenera o projeto Vivado (se necessário)
# 2. Compila o bitstream
# 3. Atualiza o PetaLinux com o novo XSA
# 4. Constrói kernel + rootfs
# 5. Gera BOOT.BIN usando FSBL original (2021.2) + novo bitstream
# 6. Copia para sd_images/ para flash
#
# Uso:
#   ./build_fresh_axi_design.sh
#
# Pré-requisitos:
#   - Vivado 2025.1
#   - PetaLinux 2025.1
#   - FSBL original 2021.2 (syn/hil/sd_images/zynq_fsbl_orig.bin)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/ebaz4205"
PETALINUX_DIR="$SCRIPT_DIR/ebaz4205_petalinux"
SD_IMAGES_DIR="$SCRIPT_DIR/sd_images"
XSA_FILE="$SCRIPT_DIR/ebaz4205.xsa"

echo "============================================================"
echo "  Build Completo — Novo Design (AXI GPIO-based) "
echo "============================================================"
echo ""

# =============================================================================
# Check dependências
# =============================================================================
if ! command -v vivado &> /dev/null; then
    echo "ERRO: Vivado não encontrado. Instale Vivado 2025.1"
    exit 1
fi

if ! command -v petalinux-build &> /dev/null; then
    echo "ERRO: PetaLinux não encontrado. Configure o ambiente:"
    echo "  source ~/xilinx/petalinux/settings.sh"
    exit 1
fi

if [[ ! -f "$SD_IMAGES_DIR/zynq_fsbl_orig.bin" ]]; then
    echo "ERRO: FSBL original não encontrado: $SD_IMAGES_DIR/zynq_fsbl_orig.bin"
    echo "   Este arquivo é OBRIGATÓRIO para boot corret ona EBAZ4205"
    echo "   Ele deve ser da toolchain 2021.2, NÃO do PetaLinux 2025.1"
    exit 1
fi

echo "✓ Dependências verificadas"
echo ""

# =============================================================================
# Step 1: Regenerar projeto Vivado
# =============================================================================
echo "Step 1: Criando projeto Vivado..."
echo "  Script: create_ebaz4205_project.tcl"
echo ""

vivado -mode batch -source create_ebaz4205_project.tcl

echo "✓ Projeto Vivado criado"
echo ""

# =============================================================================
# Step 2: Sintetizar + Implementar + Bitstream
# =============================================================================
echo "Step 2: Síntese + Implementação + Bitstream"
echo "  Script: run_impl_export.tcl"
echo "  (Isso pode levar 20-60 minutos)"
echo ""

vivado -mode batch -source run_impl_export.tcl

if [[ ! -f "$XSA_FILE" ]]; then
    echo "ERRO: XSA não foi gerado em: $XSA_FILE"
    exit 1
fi

echo "✓ XSA gerado: $XSA_FILE"
echo "  Tamanho: $(du -h $XSA_FILE | cut -f1)"
echo ""

# =============================================================================
# Step 3: Atualizar PetaLinux
# =============================================================================
echo "Step 3: Atualizando PetaLinux com novo XSA..."
echo "  (Preserva configuração do sistema)"
echo ""

cd "$PETALINUX_DIR"

# Copiar XSA para o diretório correto
cp "$XSA_FILE" project-spec/hw-description/system.xsa
cp "$XSA_FILE" project-spec/hw-description/system.hdf

# Regenerar device-tree e outros componentes
petalinux-config --get-hw-description project-spec/hw-description/

echo "✓ PetaLinux atualizado"
echo ""

# =============================================================================
# Step 4: Build PetaLinux (kernel + rootfs)
# =============================================================================
echo "Step 4: Build PetaLinux (kernel + rootfs)..."
echo "  (Isso pode levar 30-90 minutos)"
echo ""

source ~/xilinx/petalinux/settings.sh
petalinux-build

echo "✓ PetaLinux build concluído"
echo ""

# =============================================================================
# Step 5: Gerar BOOT.BIN com FSBL original
# =============================================================================
echo "Step 5: Gerando BOOT.BIN..."
echo "  Usando FSBL original (2021.2) + novo bitstream"
echo ""

PETALINUX_IMAGES="$PETALINUX_DIR/images/linux"
FSBL_ORIG="$SD_IMAGES_DIR/zynq_fsbl_orig.bin"
BOOT_BIN="$SD_IMAGES_DIR/BOOT.BIN"

# Criar arquivo BIF para bootgen
BIF_FILE="/tmp/ebaz4205.bif"
cat > "$BIF_FILE" <<EOF
all:
{
    $(FSBL_ORIG)
    [destination device=cpu0]
    [file-type=fpga] $PROJECT_DIR/ebaz4205/ebaz4205.runs/impl_1/ebaz4205_wrapper.bit
    [destination device=cpu0]
    [file-type=binary] $PETALINUX_IMAGES/u-boot.elf
    [destination device=cpu0]
    [file-type=bootimage] $PETALINUX_IMAGES/image.ub
}
EOF

# Gerar BOOT.BIN
bootgen -image "$BIF_FILE" -arch zynq -o i "$BOOT_BIN" -w

# Copiar outros arquivos
cp "$PETALINUX_DIR/images/linux/boot.scr" "$SD_IMAGES_DIR/"
cp "$PETALINUX_DIR/images/linux/image.ub" "$SD_IMAGES_DIR/"
cp "$PETALINUX_DIR/images/linux/rootfs.tar.gz" "$SD_IMAGES_DIR/"

# Limpar temp
rm -f "$BIF_FILE"

echo "✓ BOOT.BIN gerado: $BOOT_BIN"
echo "  Tamanho: $(du -h $BOOT_BIN | cut -f1)"
echo ""

# =============================================================================
# Step 6: Resumo
# =============================================================================
echo "============================================================"
echo "  ✅ Build Completo Concluído!"
echo "============================================================"
echo ""
echo "  Imagens geradas em: $SD_IMAGES_DIR/"
echo "    - BOOT.BIN           $(ls -lh $SD_IMAGES_DIR/BOOT.BIN | awk '{print $5}')"
echo "    - boot.scr           $(ls -lh $SD_IMAGES_DIR/boot.scr | awk '{print $5}')"
echo "    - image.ub           $(ls -lh $SD_IMAGES_DIR/image.ub | awk '{print $5}')"
echo "    - rootfs.tar.gz      $(ls -lh $SD_IMAGES_DIR/rootfs.tar.gz | awk '{print $5}')"
echo ""
echo "  Próximo passo:"
echo "    sudo $SCRIPT_DIR/flash_sd.sh /dev/sdX"
echo ""
echo "  OBS: Este build usa o NOVO design (AXI GPIO-based)"
echo "       Se quiser usar o design antigo (April 12), use:"
echo "        git checkout a4cf279 -- syn/hil/sd_images/"
echo ""
