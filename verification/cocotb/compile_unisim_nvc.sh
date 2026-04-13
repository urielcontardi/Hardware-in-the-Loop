#!/usr/bin/env bash
# =============================================================================
# compile_unisim_nvc.sh — Compile Xilinx UNISIM library for NVC simulator
# =============================================================================
#
# Compiles the Xilinx UNISIM VHDL sources (including DSP48E1 and DSP48E2)
# into a local NVC work library so simulations can use the real DSP primitives
# instead of the behavioral stub (BilienarSolverUnit_DSP.vhd).
#
# Usage:
#   ./compile_unisim_nvc.sh [--lib-dir <dir>] [--vivado <path>]
#
# Options:
#   --lib-dir <dir>   Output library directory (default: ./libs/nvc/unisim)
#   --vivado  <path>  Vivado installation root (default: /opt/Xilinx/2025.1)
#
# After running this script, simulations can be launched with DSP48=1:
#   make tim-ref SIM=nvc DSP48=1
# =============================================================================
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/libs/nvc/unisim"
VIVADO="${VIVADO:-/opt/Xilinx/2025.1}"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lib-dir)  LIB_DIR="$2"; shift 2 ;;
        --vivado)   VIVADO="$2";  shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Validate Vivado path ──────────────────────────────────────────────────────
UNISIM_SRC="${VIVADO}/data/vhdl/src/unisims"
if [[ ! -d "${UNISIM_SRC}" ]]; then
    echo "ERROR: UNISIM source directory not found: ${UNISIM_SRC}" >&2
    echo "       Set VIVADO env var or use --vivado <path>" >&2
    exit 1
fi

# ── Print banner ──────────────────────────────────────────────────────────────
echo ""
echo "=== Compiling UNISIM for NVC ==="
echo "  Vivado  : ${VIVADO}"
echo "  Lib dir : ${LIB_DIR}"
echo ""

# ── Prepare output directory ──────────────────────────────────────────────────
mkdir -p "${LIB_DIR}"

NVC="nvc --std=08 -M 128m --work=unisim:${LIB_DIR}"

# ── 1. Package file (UNISIM_VPKG) ─────────────────────────────────────────────
echo "[1/4] Compiling unisim_VPKG.vhd ..."
${NVC} -a "${UNISIM_SRC}/unisim_VPKG.vhd" 2>&1 | grep -v "^$" || true

# ── 2. Component declarations (UNISIM_VCOMP) ──────────────────────────────────
echo "[2/4] Compiling unisim_VCOMP.vhd ..."
${NVC} -a "${UNISIM_SRC}/unisim_VCOMP.vhd" 2>&1 | grep -v "^$" || true

# ── 3. DSP48 primitives ───────────────────────────────────────────────────────
echo "[3/4] Compiling DSP48 primitives ..."

DSP_FILES=(
    "DSP48E1.vhd"   # Xilinx Series 7 (Artix-7, Kintex-7, Virtex-7)
    "DSP48E2.vhd"   # Xilinx UltraScale / UltraScale+
)

for f in "${DSP_FILES[@]}"; do
    fpath="${UNISIM_SRC}/primitive/${f}"
    if [[ -f "${fpath}" ]]; then
        echo "    ${f} ..."
        ${NVC} -a "${fpath}" 2>&1 | grep -v "^$" || true
    else
        echo "    ${f} ... SKIPPED (not found in ${UNISIM_SRC}/primitive/)"
    fi
done

# ── 4. Optional: auxiliary DSP support primitives ─────────────────────────────
echo "[4/4] Compiling auxiliary DSP support files ..."

AUX_FILES=(
    "DSP_A_B_DATA.vhd"
    "DSP_ALU.vhd"
    "DSP_C_DATA.vhd"
    "DSP_MULTIPLIER.vhd"
    "DSP_OUTPUT.vhd"
    "DSP_PREADD_DATA.vhd"
    "DSP_PATTERN_DETECT.vhd"
    "DSP_PRE_ADDSUB.vhd"
)

for f in "${AUX_FILES[@]}"; do
    fpath="${UNISIM_SRC}/primitive/${f}"
    if [[ -f "${fpath}" ]]; then
        echo "    ${f} ..."
        ${NVC} -a "${fpath}" 2>&1 | grep -v "^$" || true
    fi
done

echo ""
echo "=== UNISIM compilation complete ==="
echo ""
echo "Run simulations with the real DSP48 model:"
echo "  make tim-ref SIM=nvc DSP48=1"
echo "  make tim-vf  SIM=nvc DSP48=1"
echo ""
