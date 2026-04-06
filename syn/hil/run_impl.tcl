# =============================================================================
# run_impl.tcl
# Synthesis + Implementation + Bitstream for HIL_EBAZ4205
#
# Usage (from project root):
#   vivado -mode batch -source syn/hil/run_impl.tcl
#
# Output:
#   syn/hil/HIL_EBAZ4205/HIL_EBAZ4205.runs/impl_1/Top_HIL_Zynq.bit
# =============================================================================

set script_dir [file dirname [file normalize [info script]]]
set proj_file  "$script_dir/HIL_EBAZ4205/HIL_EBAZ4205.xpr"

if {![file exists $proj_file]} {
    puts "ERROR: Project not found. Run 'make vivado-project' first."
    exit 1
}

open_project $proj_file

puts "============================================"
puts " HIL_EBAZ4205 — Synthesis + Implementation"
puts "  Strategy: 200 MHz aggressive timing"
puts "============================================"

# ── Reset all runs (clear OOC IP cache + previous results) ───────────────────
puts "\n\[0/3\] Resetting runs (clearing 100 MHz cache)..."
foreach ip_run [get_runs -filter {IS_SYNTHESIS && SRCSET != sources_1}] {
    puts "  Reset IP run: $ip_run"
    reset_run $ip_run
}
reset_run synth_1
reset_run impl_1
puts "  All runs reset."

# ── Aggressive synthesis strategy ────────────────────────────────────────────
# PerformanceOptimized: aggressive FSM encoding, resource sharing for timing.
# RETIMING true: enables register retiming across DSP/CARRY/LUT boundaries.
#   This is required for ClarkeTransform: Vivado must absorb the Stage-2
#   sum registers into DSP AREG=1 and the Stage-3 multiply result into
#   MREG=1. Without retiming the wide (42×43-bit) multi-DSP cascade is
#   combinatorial within one clock period, causing ~1.3 ns setup violation.
set_property strategy "Flow_PerfOptimized_high" [get_runs synth_1]
set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE  PerformanceOptimized [get_runs synth_1]
# -global_retiming: Vivado 2020+ flag (replaces deprecated ARGS.RETIMING).
# Enables register retiming across DSP/CARRY/LUT boundaries so that
# ClarkeTransform Stage-2 sum registers are absorbed into DSP AREG=1 and
# the Stage-3 multiply registers into DSP MREG=1.
set_property STEPS.SYNTH_DESIGN.ARGS.MORE_OPTIONS {-global_retiming} [get_runs synth_1]
puts "  Synthesis: Flow_PerfOptimized_high + PerformanceOptimized + global_retiming"

# ── Aggressive implementation strategy ───────────────────────────────────────
# ExtraNetDelay_high placement + AggressiveExplore routing + post-route physopt
set_property STEPS.OPT_DESIGN.ARGS.DIRECTIVE              Explore              [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE            ExtraNetDelay_high   [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED             true                 [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE         AggressiveExplore    [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE            AggressiveExplore    [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED  true                 [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveExplore [get_runs impl_1]
puts "  Implementation: ExtraNetDelay_high + AggressiveExplore + post-route physopt"

# ── Synthesis ────────────────────────────────────────────────────────────────
puts "\n\[1/3\] Launching synthesis..."
launch_runs synth_1 -jobs 4
wait_on_run synth_1

set synth_status [get_property STATUS [get_runs synth_1]]
set synth_progress [get_property PROGRESS [get_runs synth_1]]
puts "  Synthesis: $synth_status  ($synth_progress)"

if {[get_property NEEDS_REFRESH [get_runs synth_1]] || $synth_progress ne "100%"} {
    puts "ERROR: Synthesis did not complete successfully."
    exit 1
}

# ── Implementation ────────────────────────────────────────────────────────────
puts "\n\[2/3\] Launching implementation..."
launch_runs impl_1 -jobs 4
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
set impl_progress [get_property PROGRESS [get_runs impl_1]]
puts "  Implementation: $impl_status  ($impl_progress)"

if {$impl_progress ne "100%"} {
    puts "ERROR: Implementation did not complete successfully."
    exit 1
}

# ── Bitstream ─────────────────────────────────────────────────────────────────
puts "\n\[3/3\] Writing bitstream..."
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

set bit_file "$script_dir/HIL_EBAZ4205/HIL_EBAZ4205.runs/impl_1/Top_HIL_Zynq.bit"
if {[file exists $bit_file]} {
    puts "\n============================================"
    puts " Bitstream ready:"
    puts " $bit_file"
    puts "============================================"
} else {
    puts "ERROR: Bitstream not found at $bit_file"
    exit 1
}

exit
