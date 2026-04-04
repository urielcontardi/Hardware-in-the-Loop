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
puts "============================================"

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
