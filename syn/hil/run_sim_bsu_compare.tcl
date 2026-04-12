# =============================================================================
# run_sim_bsu_compare.tcl
# Runs tb_BSU_StubVsIP: BilinearSolverUnit side-by-side with stub vs IP DSP.
#
# Both DUT instances share identical inputs; checkers verify that:
#   busy_stub  == busy_ip  (timing identity)
#   result_stub == result_ip (numeric identity)
#
# Usage:  vivado -mode batch -source syn/hil/run_sim_bsu_compare.tcl
# Output: syn/hil/tb_BSU_StubVsIP.vcd  (open with GTKWave)
# =============================================================================

set script_dir [file normalize [file dirname [info script]]]
set proj_file  "$script_dir/ebaz4205/ebaz4205.xpr"
set root_dir   [file normalize "$script_dir/../.."]

if {![file exists $proj_file]} {
    puts "ERROR: Project not found — run 'make vivado-project' first."
    exit 1
}

puts "============================================"
puts " Opening project: $proj_file"
puts "============================================"
open_project $proj_file

set_property target_simulator XSim [current_project]

# ── Create / refresh sim_bsu_compare fileset ─────────────────────────────────
if {[get_filesets -quiet sim_bsu_compare] eq ""} {
    puts "Creating fileset sim_bsu_compare..."
    create_fileset -simset sim_bsu_compare

    # Same RTL sources as sim_compare (all except IP synth stubs)
    foreach f [get_files -of_objects [get_fileset sources_1]] {
        if {![string match "*/BilienarSolverUnit_DSP/synth*" $f]} {
            add_files -fileset sim_bsu_compare -norecurse $f
        }
    }

    # arch-only behavior file (adds "behavior" arch to IP's entity declaration)
    add_files -fileset sim_bsu_compare -norecurse \
        $root_dir/src/tb/BilienarSolverUnit_DSP_behavior.vhd

    # Test architectures and testbench
    add_files -fileset sim_bsu_compare -norecurse \
        $root_dir/src/tb/BilinearSolverUnit_TestArch.vhd
    add_files -fileset sim_bsu_compare -norecurse \
        $root_dir/src/tb/tb_BSU_StubVsIP.vhd

    set_property top     tb_BSU_StubVsIP [get_filesets sim_bsu_compare]
    set_property top_lib xil_defaultlib  [get_filesets sim_bsu_compare]
    update_compile_order -fileset sim_bsu_compare
    puts "  sim_bsu_compare created."
} else {
    puts "Fileset sim_bsu_compare already exists — using as-is."
}

set_property xsim.simulate.log_all_signals true [get_filesets sim_bsu_compare]

# ── Step 1: compile + elaborate + simulate ────────────────────────────────────
puts "\n=== \[1/2\] Simulation (BSU stub vs IP comparison) ==="
launch_simulation -simset sim_bsu_compare -mode behavioral
run all
close_sim

# ── Step 2: re-run snapshot → export VCD for GTKWave ─────────────────────────
set sim_dir  "$script_dir/ebaz4205/ebaz4205.sim/sim_bsu_compare/behav/xsim"
set vcd_file [file normalize "$script_dir/tb_BSU_StubVsIP.vcd"]
set tcl_file "$sim_dir/export_bsu_vcd.tcl"

set f [open $tcl_file w]
puts $f "open_vcd {$vcd_file}"
puts $f "log_vcd \[get_objects -r /tb_BSU_StubVsIP/*\]"
puts $f "restart"
puts $f "run all"
puts $f "flush_vcd"
puts $f "close_vcd"
puts $f "quit"
close $f

puts "\n=== \[2/2\] Exporting VCD waveform ==="
set saved_dir [pwd]
cd $sim_dir
catch {exec xsim tb_BSU_StubVsIP_behav -tclbatch export_bsu_vcd.tcl -log export_bsu_vcd.log} result
puts $result
cd $saved_dir

if {[file exists $vcd_file]} {
    puts "\n============================================"
    puts " Waveform ready:"
    puts "   $vcd_file"
    puts " Suggested GTKWave layout:"
    puts "   /tb_BSU_StubVsIP/sysclk"
    puts "   /tb_BSU_StubVsIP/start_i"
    puts "   /tb_BSU_StubVsIP/busy_stub   ← should match busy_ip"
    puts "   /tb_BSU_StubVsIP/busy_ip"
    puts "   /tb_BSU_StubVsIP/result_stub ← should match result_ip"
    puts "   /tb_BSU_StubVsIP/result_ip"
    puts " Open with:"
    puts "   gtkwave $vcd_file"
    puts "============================================"
} else {
    puts "WARNING: VCD not generated — check $sim_dir/export_bsu_vcd.log"
}

exit
