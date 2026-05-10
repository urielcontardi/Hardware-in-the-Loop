#!/usr/bin/env bash
# =============================================================================
# deploy_board.sh — Envia bitstream + binários para a EBAZ4205
# =============================================================================
# Uso:
#   ./scripts/deploy_board.sh
#   IP=192.168.1.50 ./scripts/deploy_board.sh
# =============================================================================

set -e

BOARD_IP="${IP:-192.168.15.12}"
BOARD_USER="petalinux"
BOARD_PASS="1234"      # ← altere aqui se necessário
BOARD_HOME="/home/petalinux"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

VIVADO_BIN="$ROOT_DIR/syn/hil/ebaz4205/ebaz4205.runs/impl_1/ebaz4205_wrapper.bit.bin"
TEST_FPGA="$ROOT_DIR/src/ps_app/test_fpga"

# ---------------------------------------------------------------------------
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=5"

scp_file() {
    local src="$1"
    local dst="$2"
    echo "  → $(basename "$src")"
    sshpass -p "$BOARD_PASS" scp $SSH_OPTS "$src" "${BOARD_USER}@${BOARD_IP}:${dst}"
}

run_board() {
    sshpass -p "$BOARD_PASS" ssh $SSH_OPTS "${BOARD_USER}@${BOARD_IP}" "$@"
}

# Executa comando com sudo no board, passando a senha via stdin
run_board_sudo() {
    sshpass -p "$BOARD_PASS" ssh $SSH_OPTS "${BOARD_USER}@${BOARD_IP}" \
        "echo '$BOARD_PASS' | sudo -S $*"
}

# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║        HIL — Deploy para EBAZ4205            ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Board: ${BOARD_USER}@${BOARD_IP}"
echo ""

# Verifica arquivos
for f in "$VIVADO_BIN" "$TEST_FPGA"; do
    if [ ! -f "$f" ]; then
        echo "ERRO: arquivo não encontrado: $f"
        echo "  Rode 'make synth' e 'make ps-build-test' primeiro."
        exit 1
    fi
done

# Verifica sshpass
if ! command -v sshpass &>/dev/null; then
    echo "ERRO: sshpass não instalado. Rode: sudo apt-get install sshpass"
    exit 1
fi

# Testa conexão
echo "Testando conexão..."
run_board "echo OK" > /dev/null
echo "  Conexão OK"
echo ""

# Copia arquivos
echo "Copiando arquivos..."
scp_file "$VIVADO_BIN"  "$BOARD_HOME/ebaz4205_wrapper.bin"
scp_file "$TEST_FPGA"   "$BOARD_HOME/test_fpga"
echo ""

# Carrega bitstream e roda smoke test
echo "Carregando bitstream na FPGA..."
run_board_sudo "fpgautil -b $BOARD_HOME/ebaz4205_wrapper.bin"
echo "  Bitstream carregado."
echo ""

echo "Rodando smoke test..."
echo "────────────────────────────────────────────────"
run_board_sudo "$BOARD_HOME/test_fpga"
echo "────────────────────────────────────────────────"
echo ""
