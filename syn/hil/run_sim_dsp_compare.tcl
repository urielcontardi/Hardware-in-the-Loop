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
set root_dir   [file normalize "$script_dir/../.."]

if {![file exists $proj_file]} {
    puts "ERROR: Project not found. Run 'make vivado-project' first."
    exit 1
}

puts "============================================"
puts " Opening project: $proj_file"
puts "============================================"
open_project $proj_file

set_property target_simulator XSim [current_project]

# ── Create / refresh sim_compare fileset ─────────────────────────────────────
if {[get_filesets -quiet sim_compare] eq ""} {
    puts "Creating fileset sim_compare..."
    create_fileset -simset sim_compare

    # BilinearSolverPkg needed by testbench (FP_TOTAL_BITS, to_fp)
    add_files -fileset sim_compare -norecurse \
        $root_dir/common/modules/bilinear_solver/src/BilinearSolverPkg.vhd

    # NOTE: BilienarSolverUnit_DSP.vhd (common/modules) is NOT added here.
    # The IP sim file already declares the entity; adding the source would
    # overwrite it with a LATENCY generic, causing a redeclaration conflict
    # in BilienarSolverUnit_DSP_behavior.vhd.

    # Self-contained stub entity (BilienarSolverUnit_DSP_Sim) — always compiled
    add_files -fileset sim_compare -norecurse \
        $root_dir/src/tb/BilienarSolverUnit_DSP_Sim.vhd
    add_files -fileset sim_compare -norecurse \
        $root_dir/src/tb/tb_DSP_StubVsIP.vhd

    set_property top     tb_DSP_StubVsIP [get_filesets sim_compare]
    set_property top_lib xil_defaultlib  [get_filesets sim_compare]
    update_compile_order -fileset sim_compare
    puts "  sim_compare created."
} else {
    puts "Fileset sim_compare already exists — using as-is."
}

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
