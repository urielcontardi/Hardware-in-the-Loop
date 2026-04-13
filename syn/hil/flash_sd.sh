#!/usr/bin/env bash
# =============================================================================
# flash_sd.sh
#
# Prepara SD card para boot Linux no EBAZ4205 (PetaLinux 2025.1)
#
# Partições criadas:
#   p1 : FAT32  256 MB  → BOOT.BIN, boot.scr, image.ub
#   p2 : EXT4   restante → rootfs
#
# Uso:
#   sudo ./flash_sd.sh /dev/sdX
# =============================================================================

set -euo pipefail

IMAGES_DIR="$(dirname "$0")/ebaz4205_petalinux/images/linux"

# ── Argumentos ────────────────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
    echo "Uso: sudo $0 /dev/sdX"
    exit 1
fi

DEV="$1"

if [[ ! -b "$DEV" ]]; then
    echo "ERRO: '$DEV' não é um block device."
    exit 1
fi

# Bloquear disco principal (NVMe/eMMC interno)
if [[ "$DEV" == /dev/nvme* ]] || [[ "$DEV" == /dev/mmcblk0 ]]; then
    echo "ERRO: '$DEV' parece ser o disco principal. Abortando."
    exit 1
fi

# ── Verificar arquivos necessários ────────────────────────────────────────────
for f in BOOT.BIN boot.scr image.ub rootfs.tar.gz; do
    if [[ ! -f "$IMAGES_DIR/$f" ]]; then
        echo "ERRO: arquivo não encontrado: $IMAGES_DIR/$f"
        exit 1
    fi
done

# ── Confirmação ───────────────────────────────────────────────────────────────
echo "======================================================"
echo " ATENÇÃO: TODOS OS DADOS EM $DEV SERÃO APAGADOS"
echo "======================================================"
lsblk "$DEV"
echo ""
read -rp "Confirma? (digite 'sim' para continuar): " CONFIRM
if [[ "$CONFIRM" != "sim" ]]; then
    echo "Abortado."
    exit 0
fi

# ── Desmontar partições existentes ────────────────────────────────────────────
echo "[1/6] Desmontando partições..."
for part in "${DEV}"?*; do
    if mountpoint -q "$part" 2>/dev/null || grep -q "^$part " /proc/mounts 2>/dev/null; then
        umount "$part" || true
    fi
done

# ── Particionar ───────────────────────────────────────────────────────────────
echo "[2/6] Particionando $DEV..."
parted -s "$DEV" mklabel msdos
parted -s "$DEV" mkpart primary fat32  1MiB  257MiB
parted -s "$DEV" mkpart primary ext4  257MiB  100%
parted -s "$DEV" set 1 boot on

# Aguardar o kernel atualizar as partições
sleep 2
partprobe "$DEV" 2>/dev/null || true
sleep 1

# Detectar nomes das partições (sdX1 ou sdXp1)
if [[ -b "${DEV}1" ]]; then
    PART1="${DEV}1"
    PART2="${DEV}2"
elif [[ -b "${DEV}p1" ]]; then
    PART1="${DEV}p1"
    PART2="${DEV}p2"
else
    echo "ERRO: não foi possível detectar as partições de $DEV"
    exit 1
fi

# ── Formatar ──────────────────────────────────────────────────────────────────
echo "[3/6] Formatando partições..."
mkfs.vfat -F 32 -n BOOT "$PART1"
mkfs.ext4 -L rootfs -F "$PART2"

# ── Montar ────────────────────────────────────────────────────────────────────
echo "[4/6] Montando partições..."
MNT_BOOT=$(mktemp -d)
MNT_ROOT=$(mktemp -d)
mount "$PART1" "$MNT_BOOT"
mount "$PART2" "$MNT_ROOT"

# ── Copiar arquivos de boot ───────────────────────────────────────────────────
echo "[5/6] Copiando imagens de boot..."
cp "$IMAGES_DIR/BOOT.BIN"  "$MNT_BOOT/"
cp "$IMAGES_DIR/boot.scr"  "$MNT_BOOT/"
cp "$IMAGES_DIR/image.ub"  "$MNT_BOOT/"
sync

# ── Extrair rootfs ────────────────────────────────────────────────────────────
echo "[6/6] Extraindo rootfs (pode demorar)..."
tar -xf "$IMAGES_DIR/rootfs.tar.gz" -C "$MNT_ROOT/"
sync

# ── Desmontar ─────────────────────────────────────────────────────────────────
umount "$MNT_BOOT"
umount "$MNT_ROOT"
rmdir  "$MNT_BOOT" "$MNT_ROOT"

echo ""
echo "======================================================"
echo " SD card pronto!"
echo "  p1 (FAT32) : BOOT.BIN, boot.scr, image.ub"
echo "  p2 (EXT4)  : rootfs"
echo ""
echo " Remova o SD, insira na EBAZ4205 e ligue a placa."
echo " Console UART: 115200 8N1 (MIO24/25 = J7 header)"
echo "======================================================"
