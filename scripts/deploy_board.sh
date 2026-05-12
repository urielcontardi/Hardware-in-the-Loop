#!/usr/bin/env bash
# =============================================================================
# deploy_board.sh — Envia bitstream + binários para a EBAZ4205
# =============================================================================
# Uso:
#   ./scripts/deploy_board.sh
#   IP=192.168.1.50 ./scripts/deploy_board.sh
# =============================================================================

set -e

BOARD_IP="${IP:-192.168.15.14}"
BOARD_USER="petalinux"
BOARD_PASS="1234"      # ← altere aqui se necessário
BOARD_HOME="/home/petalinux"
SKIP_BITSTREAM="${SKIP_BITSTREAM:-0}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

VIVADO_BIN="$ROOT_DIR/syn/hil/ebaz4205/ebaz4205.runs/impl_1/ebaz4205_wrapper.bit.bin"
TEST_FPGA="$ROOT_DIR/src/ps_app/test_fpga"
HIL_CTRL="$ROOT_DIR/src/ps_app/hil_controller"

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
    local cmd="$*"
    local quoted_cmd
    printf -v quoted_cmd '%q' "$cmd"
    sshpass -p "$BOARD_PASS" ssh $SSH_OPTS "${BOARD_USER}@${BOARD_IP}" \
        "printf '%s\n' '$BOARD_PASS' | sudo -S -- sh -c $quoted_cmd"
}

# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║        HIL — Deploy para EBAZ4205            ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Board: ${BOARD_USER}@${BOARD_IP}"
echo ""

# Verifica / compila arquivos necessários
if [ ! -f "$VIVADO_BIN" ]; then
    echo "ERRO: bitstream não encontrado: $VIVADO_BIN"
    echo "  Rode: make synth"
    exit 1
fi

if [ ! -f "$TEST_FPGA" ]; then
    echo "  test_fpga não encontrado — compilando..."
    make -C "$ROOT_DIR" ps-build-test
fi

if [ ! -f "$HIL_CTRL" ]; then
    echo "  hil_controller não encontrado — compilando..."
    make -C "$ROOT_DIR" ps-build
fi

# Verifica sshpass
if ! command -v sshpass &>/dev/null; then
    echo "ERRO: sshpass não instalado. Rode: sudo apt-get install sshpass"
    exit 1
fi

# Testa conexão
echo "Testando conexão..."
if ! run_board "echo OK" > /dev/null 2>&1; then
    echo "ERRO: não foi possível conectar em ${BOARD_USER}@${BOARD_IP}"
    echo "  Verifique se a board está ligada e na rede."
    echo "  Para usar outro IP: IP=<endereço> ./scripts/deploy_board.sh"
    exit 1
fi
echo "  Conexão OK"
echo ""

# Mata processos e remove binários antes de copiar
# (não é possível sobrescrever binário em execução no Linux — apagar libera o inode)
echo "Parando processos e removendo binários anteriores..."
run_board_sudo "PID=\$(pidof hil_controller); if [ -n \"\$PID\" ]; then kill -9 \$PID; fi; true"
run_board_sudo "PID=\$(pidof test_fpga); if [ -n \"\$PID\" ]; then kill -9 \$PID; fi; true"
sleep 1
run_board_sudo "rm -f $BOARD_HOME/hil_controller $BOARD_HOME/test_fpga"

# Copia arquivos
echo "Copiando arquivos..."
scp_file "$VIVADO_BIN"  "$BOARD_HOME/ebaz4205_wrapper.bin"
scp_file "$TEST_FPGA"   "$BOARD_HOME/test_fpga"
scp_file "$HIL_CTRL"    "$BOARD_HOME/hil_controller"
echo ""

# Carrega bitstream
if [ "$SKIP_BITSTREAM" = "1" ]; then
    echo "Pulando carga do bitstream (SKIP_BITSTREAM=1)."
else
    echo "Carregando bitstream na FPGA..."
    run_board_sudo "fpgautil -b $BOARD_HOME/ebaz4205_wrapper.bin"
    echo "  Bitstream carregado."
fi
echo ""

# Smoke test
echo "Rodando smoke test..."
echo "────────────────────────────────────────────────"
if ! run_board_sudo "$BOARD_HOME/test_fpga"; then
    echo "────────────────────────────────────────────────"
    echo "AVISO: smoke test falhou — hil_controller não será iniciado."
    exit 1
fi
echo "────────────────────────────────────────────────"
echo ""

# Inicia hil_controller em background. Isso evita deixar o daemon preso ao PTY
# do SSH e facilita publicar/controlar via gateway web.
echo "Iniciando hil_controller..."
echo "────────────────────────────────────────────────"
run_board_sudo "nohup $BOARD_HOME/hil_controller > $BOARD_HOME/hil_controller.log 2>&1 &"
sleep 1
run_board "tail -n 8 $BOARD_HOME/hil_controller.log"
echo "────────────────────────────────────────────────"
echo "  Rodando em background. Logs:"
echo "    ssh ${BOARD_USER}@${BOARD_IP} 'tail -f $BOARD_HOME/hil_controller.log'"
echo ""
