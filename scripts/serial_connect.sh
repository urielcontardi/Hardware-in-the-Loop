#!/usr/bin/env bash
# List USB serial ports and open the selected port with picocom.
#
# Usage:
#   ./scripts/serial_connect.sh            # default baud rate: 115200
#   ./scripts/serial_connect.sh 9600       # custom baud rate

BAUD="${1:-115200}"

# ── Stop previous picocom instances ────────────────────────────────────────────
if pgrep -x picocom > /dev/null; then
    echo "Encerrando picocom aberto anteriormente..."
    pkill picocom
    sleep 0.5
fi

# ── Ensure that the FTDI driver is loaded ──────────────────────────────────────
if ! lsmod | grep -q ftdi_sio; then
    echo "Carregando módulo ftdi_sio..."
    sudo modprobe ftdi_sio
    sleep 0.5
fi

# ── Collect devices ────────────────────────────────────────────────────────────
mapfile -t PORTS < <(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null)

if [[ ${#PORTS[@]} -eq 0 ]]; then
    echo "Nenhuma porta serial USB encontrada em /dev/ttyUSB* ou /dev/ttyACM*"
    exit 1
fi

# ── List devices with driver/product details from udevadm ─────────────────────
echo ""
echo "Portas seriais disponíveis:"
echo "─────────────────────────────────────────────────"
for i in "${!PORTS[@]}"; do
    PORT="${PORTS[$i]}"
    INFO=$(udevadm info --query=property --name="$PORT" 2>/dev/null \
           | grep -E "^ID_MODEL=|^ID_VENDOR=|^ID_USB_DRIVER=" \
           | sed 's/^ID_MODEL=//; s/^ID_VENDOR=//; s/^ID_USB_DRIVER=//' \
           | tr '\n' ' ')
    printf "  [%d] %-15s %s\n" "$((i+1))" "$PORT" "$INFO"
done
echo "─────────────────────────────────────────────────"
echo ""

# ── Selection ─────────────────────────────────────────────────────────────────
if [[ ${#PORTS[@]} -eq 1 ]]; then
    SELECTED="${PORTS[0]}"
    echo "Apenas uma porta encontrada — conectando em $SELECTED"
else
    read -rp "Escolha [1-${#PORTS[@]}]: " CHOICE
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || (( CHOICE < 1 || CHOICE > ${#PORTS[@]} )); then
        echo "Opção inválida."
        exit 1
    fi
    SELECTED="${PORTS[$((CHOICE-1))]}"
fi

# ── Check permissions ─────────────────────────────────────────────────────────
if [[ ! -r "$SELECTED" || ! -w "$SELECTED" ]]; then
    echo "Sem permissão em $SELECTED — adicionando usuário ao grupo 'dialout':"
    echo "  sudo usermod -aG dialout $USER && newgrp dialout"
    echo "Ou rode com sudo desta vez:"
    echo "  sudo picocom -b $BAUD $SELECTED"
    exit 1
fi

# ── Connect ───────────────────────────────────────────────────────────────────
echo "Conectando em $SELECTED @ ${BAUD} baud"
echo "(Para sair: Ctrl+A  Ctrl+X)"
echo ""
exec picocom -b "$BAUD" "$SELECTED"
