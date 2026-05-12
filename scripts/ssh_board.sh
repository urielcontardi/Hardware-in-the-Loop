#!/usr/bin/env bash
# ssh_board.sh — abre sessão SSH na EBAZ4205
#
# Uso:
#   ./scripts/ssh_board.sh
#   IP=192.168.1.50 ./scripts/ssh_board.sh

BOARD_IP="${IP:-192.168.15.14}"
BOARD_USER="petalinux"
BOARD_PASS="1234"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=5"

if ! command -v sshpass &>/dev/null; then
    echo "ERRO: sshpass não instalado. Rode: sudo apt-get install sshpass"
    exit 1
fi

echo "Conectando em ${BOARD_USER}@${BOARD_IP} ..."
sshpass -p "$BOARD_PASS" ssh $SSH_OPTS "${BOARD_USER}@${BOARD_IP}"
