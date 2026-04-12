# =============================================================================
# run_sim_dsp_compare.tcl
# Runs tb_DSP_StubVsIP: direct side-by-side comparison of the behavioral stub
# (BilienarSolverUnit_DSP / behavior) vs the Xilinx mult_gen IP sim model
# (BilienarSolverUnit_DSP / bilienarsolverunit_dsp_arch).
#
# Usage:  vivado -mode batch -source syn/hil/run_sim_dsp_compare.tcl
# Output: syn/hil/tb_DSP_StubVsIP.vcd  (open with GTKWave)
# =============================================================================

set script_dir [file normalize [file dirname [info script]]]
set proj_file  "$script_dir/ebaz4205/ebaz4205.xpr"

if {![file exists $proj_file]} {
    puts "ERROR: Project not found. Run 'make vivado-project' first."
    exit 1
}

puts "============================================"
puts " Opening project: $proj_file"
puts "============================================"
open_project $proj_file

set_property target_simulator XSim [current_project]

# Log all signals so the WDB is complete (needed for VCD export step below)
set_property xsim.simulate.log_all_signals true [get_filesets sim_compare]

# ── Step 1: compile + elaborate + simulate (PASS/FAIL check) ─────────────────
puts "\n=== \[1/2\] Simulation (stub vs IP comparison) ==="
launch_simulation -simset sim_compare -mode behavioral
run all
close_sim

# ── Step 2: re-run snapshot → export VCD for GTKWave ─────────────────────────
set sim_dir  "$script_dir/ebaz4205/ebaz4205.sim/sim_compare/behav/xsim"
set vcd_file [file normalize "$script_dir/tb_DSP_StubVsIP.vcd"]
set tcl_file "$sim_dir/export_vcd.tcl"

set f [open $tcl_file w]
puts $f "open_vcd {$vcd_file}"
puts $f "log_vcd \[get_objects -r /tb_DSP_StubVsIP/*\]"
puts $f "restart"
puts $f "run all"
puts $f "flush_vcd"
puts $f "close_vcd"
puts $f "quit"
close $f

puts "\n=== \[2/2\] Exporting VCD waveform ==="
set saved_dir [pwd]
cd $sim_dir
catch {exec xsim tb_DSP_StubVsIP_behav -tclbatch export_vcd.tcl -log export_vcd.log} result
puts $result
cd $saved_dir

if {[file exists $vcd_file]} {
    puts "\n============================================"
    puts " Waveform ready:"
    puts "   $vcd_file"
    puts " Open with:"
    puts "   gtkwave $vcd_file"
    puts "============================================"
} else {
    puts "WARNING: VCD not generated — check $sim_dir/export_vcd.log"
}

exit
