#!/usr/bin/env bash
# =============================================================================
# jtag_reset.sh — Reset EBAZ4205 (Zynq-7010) via JTAG using xsdb
# =============================================================================
#
# Usage:
#   ./jtag_reset.sh              # system reset (default)
#   ./jtag_reset.sh --halt       # reset and halt at first instruction
#   ./jtag_reset.sh --cores      # reset only PS cores
#   ./jtag_reset.sh --list       # list available JTAG targets
#
# Requirements:
#   - Vivado/Vitis installed and sourced (xsdb must be in PATH)
#   - JTAG adapter connected (e.g. Digilent JTAG-HS2 or onboard USB-JTAG)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Check xsdb
# ---------------------------------------------------------------------------
if ! command -v xsdb &>/dev/null; then
    error "xsdb not found. Source your Vivado/Vitis settings first:"
    error "  source /opt/Xilinx/Vivado/<version>/settings64.sh"
    error "  # or"
    error "  source /opt/Xilinx/Vitis/<version>/settings64.sh"
    exit 1
fi

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
MODE="system"   # default

case "${1:-}" in
    --halt)   MODE="halt"   ;;
    --cores)  MODE="cores"  ;;
    --list)   MODE="list"   ;;
    --help|-h)
        grep '^#' "$0" | grep -v '#!/' | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    "")       MODE="system" ;;
    *)
        error "Unknown option: $1"
        echo "Use --help for usage."
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# TCL helper: selects the first ARM/APU target found in the JTAG chain.
# Falls back to target index 2 (typical for Zynq-7) if filter returns nothing.
# Note: no square brackets inside puts strings — TCL interprets [] as commands.
# ---------------------------------------------------------------------------
SELECT_TARGET='
proc select_arm_target {} {
    set found [targets -filter {name =~ "*APU*" || name =~ "*ARM*" || name =~ "*A9*"}]
    if {[llength $found] > 0} {
        targets -set [lindex $found 0]
    } else {
        # Zynq-7 JTAG chain: 1=jtag, 2=APU, 3=xc7z010
        catch { targets -set 2 }
    }
}
'

# ---------------------------------------------------------------------------
# Build xsdb TCL per mode
# ---------------------------------------------------------------------------
case "$MODE" in
    list)
        info "Listing JTAG targets..."
        XSDB_CMD="${SELECT_TARGET}
            connect
            after 500
            puts {=== Available targets ===}
            targets
            disconnect
        "
        ;;
    halt)
        info "Resetting Zynq-7010 via JTAG (reset + halt)..."
        XSDB_CMD="${SELECT_TARGET}
            connect
            after 500
            select_arm_target
            rst -system
            after 300
            stop
            puts {Reset+halt complete. CPU is stopped.}
            disconnect
        "
        ;;
    cores)
        info "Resetting PS cores only (Zynq-7010)..."
        XSDB_CMD="${SELECT_TARGET}
            connect
            after 500
            select_arm_target
            rst -cores
            puts {Core reset complete.}
            disconnect
        "
        ;;
    system)
        info "Performing system reset on Zynq-7010..."
        XSDB_CMD="${SELECT_TARGET}
            connect
            after 500
            select_arm_target
            rst -system
            after 500
            puts {System reset complete. Board is running.}
            disconnect
        "
        ;;
esac

# ---------------------------------------------------------------------------
# Run xsdb
# ---------------------------------------------------------------------------
echo ""
xsdb <<EOF
$XSDB_CMD
EOF

echo ""
info "Done."
