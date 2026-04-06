# =============================================================================
# run_sim_clarke.tcl
# Runs tb_ClarkeTransform: Tests behavioral Clarke Transform (4-cycle latency)
#
# Validates:
#   - Clarke transform equations: alpha=(2/3)(a-b/2-c/2), beta=(1/√3)(b-c), zero=(1/3)(a+b+c)
#   - 5-stage pipeline, 4-cycle input-to-output latency:
#       Stage 0: input reg | Stage 1: sums | Stage 2: multiply
#       Stage 3: P-reg     | Stage 4: output reg
#   - Fixed-point arithmetic (Q16.16 format)
#   - Vivado auto-infers DSP48E1 from behavioral multiplication
#
# Usage:  vivado -mode batch -source syn/hil/run_sim_clarke.tcl
# Output: syn/hil/tb_ClarkeTransform.vcd  (open with GTKWave)
# =============================================================================

set script_dir [file normalize [file dirname [info script]]]
set root_dir   [file normalize "$script_dir/../.."]
set proj_file  "$script_dir/HIL_EBAZ4205/HIL_EBAZ4205.xpr"

if {![file exists $proj_file]} {
    puts "ERROR: Project not found."
    puts "Expected: $proj_file"
    puts "Run 'make vivado-project' or create HIL project first."
    exit 1
}

puts "============================================"
puts " Opening project: $proj_file"
puts "============================================"
open_project $proj_file

set_property target_simulator XSim [current_project]

# ── Create / refresh sim_clarke fileset ─────────────────────────────────────
if {[get_filesets -quiet sim_clarke] eq ""} {
    puts "Creating fileset sim_clarke..."
    create_fileset -simset sim_clarke

    # Add ClarkeTransform source
    add_files -fileset sim_clarke -norecurse \
        $root_dir/common/modules/clarke_transform/src/ClarkeTransform.vhd

    # Add testbench
    add_files -fileset sim_clarke -norecurse \
        $root_dir/common/modules/clarke_transform/test/tb_ClarkeTransform.vhd

    set_property top     tb_ClarkeTransform [get_filesets sim_clarke]
    set_property top_lib xil_defaultlib     [get_filesets sim_clarke]
    update_compile_order -fileset sim_clarke
    puts "  sim_clarke created."
} else {
    puts "Fileset sim_clarke already exists — using as-is."
}

set_property xsim.simulate.log_all_signals true [get_filesets sim_clarke]

# ── Step 1: compile + elaborate + simulate ──────────────────────────────────
puts "\n=== [1/2] Simulation (ClarkeTransform behavioral, 4-cycle latency) ==="
launch_simulation -simset sim_clarke -mode behavioral
run all
close_sim

# ── Step 2: re-run snapshot → export VCD for GTKWave ────────────────────────
set sim_dir  "$script_dir/HIL_EBAZ4205/HIL_EBAZ4205.sim/sim_clarke/behav/xsim"
set vcd_file [file normalize "$script_dir/tb_ClarkeTransform.vcd"]
set tcl_file "$sim_dir/export_clarke_vcd.tcl"

set f [open $tcl_file w]
puts $f "open_vcd {$vcd_file}"
puts $f "log_vcd \[get_objects -r /tb_ClarkeTransform/*\]"
puts $f "restart"
puts $f "run all"
puts $f "flush_vcd"
puts $f "close_vcd"
puts $f "quit"
close $f

puts "\n=== [2/2] Exporting VCD waveform ==="
set saved_dir [pwd]
cd $sim_dir
catch {exec xsim tb_ClarkeTransform_behav -tclbatch export_clarke_vcd.tcl -log export_clarke_vcd.log} result
puts $result
cd $saved_dir

if {[file exists $vcd_file]} {
    puts "\n============================================"
    puts " Waveform ready:"
    puts "   $vcd_file"
    puts " Suggested GTKWave signals:"
    puts "   /tb_ClarkeTransform/clk_tb"
    puts "   /tb_ClarkeTransform/data_valid_i_tb"
    puts "   /tb_ClarkeTransform/data_valid_o_tb ← should be 4 cycles after input"
    puts "   /tb_ClarkeTransform/a_real_tb"
    puts "   /tb_ClarkeTransform/b_real_tb"
    puts "   /tb_ClarkeTransform/c_real_tb"
    puts "   /tb_ClarkeTransform/alpha_real_tb"
    puts "   /tb_ClarkeTransform/beta_real_tb"
    puts "   /tb_ClarkeTransform/zero_real_tb"
    puts "   /tb_ClarkeTransform/UUT_ClarkeTransform/validReg ← 4-bit valid tracker (5-stage pipeline)"
    puts " Open with:"
    puts "   gtkwave $vcd_file"
    puts "============================================"
    puts ""
    puts "Expected Results (from test cases):"
    puts "  Test 1 (balanced a=100, b=-50, c=-50):"
    puts "    alpha ≈ 100.0, beta ≈ 0.0, zero ≈ 0.0"
    puts "  Test 2 (unbalanced a=100, b=0, c=0):"
    puts "    alpha ≈ 66.7, beta ≈ 0.0, zero ≈ 33.3"
    puts "  Test 3 (common-mode a=50, b=50, c=50):"
    puts "    alpha ≈ 0.0, beta ≈ 0.0, zero ≈ 50.0"
    puts "  Test 4 (zeros a=0, b=0, c=0):"
    puts "    alpha ≈ 0.0, beta ≈ 0.0, zero ≈ 0.0"
    puts ""
    puts "Latency Check:"
    puts "  Measure data_valid_i rising edge → data_valid_o rising edge"
    puts "  Expected: 4 clock cycles (40 ns @ 10 ns period)"
} else {
    puts "WARNING: VCD not generated — check $sim_dir/export_clarke_vcd.log"
}

exit
