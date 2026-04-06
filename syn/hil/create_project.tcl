# =============================================================================
# create_project.tcl
# Vivado project creation for EBAZ4205 (Zynq-7010)
#
# Usage (from syn/hil/):
#   vivado -mode batch -source create_project.tcl
#   vivado -mode tcl  -source create_project.tcl
#
# Result:
#   syn/hil/HIL_EBAZ4205/HIL_EBAZ4205.xpr
# =============================================================================

set script_dir [file dirname [file normalize [info script]]]
set root_dir   [file normalize "$script_dir/../.."]
set proj_name  "HIL_EBAZ4205"
set proj_dir   "$script_dir/$proj_name"
set part       "xc7z010clg400-1"

puts "============================================"
puts " HIL EBAZ4205 - Creating Vivado Project"
puts " Part : $part"
puts " Dir  : $proj_dir"
puts "============================================"

# Remove existing project
if {[file exists $proj_dir]} {
    puts "Removing existing project..."
    file delete -force $proj_dir
}

# -----------------------------------------------------------------------------
# Create project
# -----------------------------------------------------------------------------
create_project $proj_name $proj_dir -part $part
set_property target_language    VHDL [current_project]
set_property simulator_language VHDL [current_project]

# -----------------------------------------------------------------------------
# RTL Sources
# -----------------------------------------------------------------------------
puts "\nAdding RTL sources..."

# Core top-level modules
add_files -norecurse [glob $root_dir/src/rtl/TIM_Solver.vhd]
add_files -norecurse [glob $root_dir/src/rtl/SerialManager.vhd]
add_files -norecurse [glob $root_dir/src/rtl/Top_HIL_Zynq.vhd]

# Common modules
# bilinear_solver: DSP stub is simulation-only — excluded from synthesis, added to sim_1
foreach mod {npc_modulator clarke_transform uart fifo edge_detector} {
    set files [glob -nocomplain $root_dir/common/modules/$mod/src/*.vhd]
    if {[llength $files] > 0} {
        add_files -norecurse $files
        puts "  Added: $mod ([llength $files] files)"
    } else {
        puts "  WARNING: No files found for $mod"
    }
}

# bilinear_solver: split synthesis vs simulation files
set bs_all [glob -nocomplain $root_dir/common/modules/bilinear_solver/src/*.vhd]
set bs_synth {}
set bs_sim   {}
foreach f $bs_all {
    if {[string match "*BilienarSolverUnit_DSP*" $f]} {
        lappend bs_sim $f
    } else {
        lappend bs_synth $f
    }
}
add_files -norecurse $bs_synth
add_files -fileset sim_1 -norecurse $bs_sim
puts "  Added: bilinear_solver ([llength $bs_synth] synth + [llength $bs_sim] sim-only)"

# Set top
set_property top Top_HIL_Zynq [current_fileset]
update_compile_order -fileset sources_1

# -----------------------------------------------------------------------------
# BilinearSolverUnit_DSP IP (mult_gen v12.0)
# Signed 42x42 → 84-bit, 7-stage pipeline, DSP48 optimized for speed
# Parameters recovered from original .xci (commit fc5e59f)
# Simulation uses BilienarSolverUnit_DSP.vhd stub (identical behavior)
# -----------------------------------------------------------------------------
puts "\nCreating BilinearSolverUnit_DSP IP..."
create_ip -name mult_gen \
          -vendor xilinx.com \
          -library ip \
          -version 12.0 \
          -module_name BilienarSolverUnit_DSP

set_property -dict [list \
    CONFIG.PortAType               {Signed}   \
    CONFIG.PortAWidth              {42}        \
    CONFIG.PortBType               {Signed}   \
    CONFIG.PortBWidth              {42}        \
    CONFIG.Multiplier_Construction {Use_Mults} \
    CONFIG.OptGoal                 {Speed}     \
    CONFIG.PipeStages              {7}         \
    CONFIG.Use_Custom_Output_Width {false}     \
    CONFIG.ClockEnable             {false}     \
    CONFIG.SyncClear               {false}     \
    CONFIG.ZeroDetect              {false}     \
] [get_ips BilienarSolverUnit_DSP]

generate_target all [get_ips BilienarSolverUnit_DSP]
puts "  IP created: BilienarSolverUnit_DSP (42x42 signed, 7 pipeline stages)"

# Override OOC clock to 5 ns (200 MHz) so the IP is synthesized and optimized
# for the actual target frequency. Without this Vivado uses the IP default
# (100 ns), which means ACOUT/PCOUT cascade paths are not pipelined correctly.
# The OOC XDC is generated under .gen/ (not .srcs/)
set ip_xci  [lindex [get_files BilienarSolverUnit_DSP.xci] 0]
set gen_dir [file normalize "$proj_dir/${proj_name}.gen/sources_1/ip/BilienarSolverUnit_DSP"]
set ooc_xdc "$gen_dir/BilienarSolverUnit_DSP_ooc.xdc"
if {[file exists $ooc_xdc]} {
    set fp [open $ooc_xdc w]
    puts $fp "# OOC clock constraint: 5 ns = 200 MHz (matches Top_HIL_Zynq FCLK)"
    puts $fp "create_clock -period 5.000 -name CLK \[get_ports CLK\]"
    close $fp
    puts "  OOC XDC overridden: 5 ns (200 MHz) → $ooc_xdc"
} else {
    puts "  WARNING: OOC XDC not found at $ooc_xdc"
}

# -----------------------------------------------------------------------------
# sim_compare — stub vs IP direct comparison (both architectures instantiated)
#   Purpose : prove stub == IP cycle-by-cycle on the same input vectors
#   Both BilienarSolverUnit_DSP architectures must be visible:
#     • bilienarsolverunit_dsp_arch — from IP sim model (entity + arch, first)
#     • behavior                    — from arch-only file (no entity, second)
#   The arch-only file avoids re-declaring the entity so xsim keeps both archs.
#   Top     : tb_DSP_StubVsIP
# -----------------------------------------------------------------------------
puts "\nConfiguring sim_compare (stub vs IP side-by-side)..."
create_fileset -simset sim_compare
# Add all RTL sources — exclude IP synth stubs (wrong entity decl for sim)
foreach f [get_files -of_objects [get_fileset sources_1]] {
    if {![string match "*/BilienarSolverUnit_DSP/synth*" $f]} {
        add_files -fileset sim_compare -norecurse $f
    }
}
# Add arch-only behavior file — compiles against the IP's entity declaration
# (no generics), avoiding entity redeclaration that would orphan IP's arch
add_files -fileset sim_compare -norecurse \
    $root_dir/src/tb/BilienarSolverUnit_DSP_behavior.vhd
# Add the comparison testbench
add_files -fileset sim_compare -norecurse $root_dir/src/tb/tb_DSP_StubVsIP.vhd
set_property top     tb_DSP_StubVsIP [get_filesets sim_compare]
set_property top_lib xil_defaultlib  [get_filesets sim_compare]
update_compile_order -fileset sim_compare
puts "  sim_compare top: tb_DSP_StubVsIP  (IP arch + behavior arch-only)"

# -----------------------------------------------------------------------------
# sim_bsu_compare — BilinearSolverUnit stub vs IP full-solver comparison
#   Both instances share identical inputs; checkers verify timing + numeric match.
#   rtl_stub arch uses BilienarSolverUnit_DSP(behavior)
#   rtl_ip   arch uses BilienarSolverUnit_DSP(bilienarsolverunit_dsp_arch)
#   Top     : tb_BSU_StubVsIP
# -----------------------------------------------------------------------------
puts "\nConfiguring sim_bsu_compare (BSU stub vs IP full-solver)..."
create_fileset -simset sim_bsu_compare
# Same RTL sources as sim_compare
foreach f [get_files -of_objects [get_fileset sources_1]] {
    if {![string match "*/BilienarSolverUnit_DSP/synth*" $f]} {
        add_files -fileset sim_bsu_compare -norecurse $f
    }
}
# arch-only behavior stub
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/BilienarSolverUnit_DSP_behavior.vhd
# Test architectures (rtl_stub / rtl_ip) and testbench
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/BilinearSolverUnit_TestArch.vhd
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/tb_BSU_StubVsIP.vhd
set_property top     tb_BSU_StubVsIP [get_filesets sim_bsu_compare]
set_property top_lib xil_defaultlib  [get_filesets sim_bsu_compare]
update_compile_order -fileset sim_bsu_compare
puts "  sim_bsu_compare top: tb_BSU_StubVsIP  (rtl_stub + rtl_ip architectures)"

# -----------------------------------------------------------------------------
# Constraints
# -----------------------------------------------------------------------------
puts "\nAdding constraints..."
add_files -fileset constrs_1 -norecurse $script_dir/ebaz4205.xdc
set_property target_constrs_file $script_dir/ebaz4205.xdc \
    [current_fileset -constrset]

# -----------------------------------------------------------------------------
# Block Design (PS7 - clock + reset only)
# -----------------------------------------------------------------------------
puts "\nCreating block design..."
source $script_dir/zynq_ps7.tcl

# Generate wrapper VHDL
make_wrapper -files [get_files zynq_ps7.bd] -top
set wrapper [lindex [get_files -of_objects [get_fileset sources_1] \
    -filter {NAME =~ *zynq_ps7_wrapper.vhd}] 0]
if {$wrapper eq ""} {
    set wrapper [glob -nocomplain \
        $proj_dir/${proj_name}.gen/sources_1/bd/zynq_ps7/hdl/zynq_ps7_wrapper.vhd \
        $proj_dir/${proj_name}.srcs/sources_1/bd/zynq_ps7/hdl/zynq_ps7_wrapper.vhd]
    set wrapper [lindex $wrapper 0]
    add_files -norecurse $wrapper
}
puts "Wrapper: $wrapper"

# Confirm top
set_property top Top_HIL_Zynq [current_fileset]
update_compile_order -fileset sources_1

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
puts "\n============================================"
puts " Project ready: $proj_dir/${proj_name}.xpr"
puts "--------------------------------------------"
puts " To open:      vivado $proj_dir/${proj_name}.xpr"
puts " To synthesize (batch):"
puts "   open_project $proj_dir/${proj_name}.xpr"
puts "   launch_runs synth_1 -jobs 4"
puts "   wait_on_run synth_1"
puts "   launch_runs impl_1 -to_step write_bitstream -jobs 4"
puts "   wait_on_run impl_1"
puts "============================================\n"
