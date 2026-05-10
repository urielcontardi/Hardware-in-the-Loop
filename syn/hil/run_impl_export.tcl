# =============================================================================
# run_impl_export.tcl
#
# Abre o projeto ebaz4205, roda síntese + implementação + bitstream e
# exporta o XSA para uso no PetaLinux.
#
# Uso:
#   /opt/Xilinx/2025.1/Vivado/bin/vivado -mode batch -source run_impl_export.tcl
# =============================================================================

set proj_file "[file normalize [file join [file dirname [info script]] ebaz4205/ebaz4205.xpr]]"
set xsa_out   "[file normalize [file join [file dirname [info script]] ebaz4205.xsa]]"

set_param general.maxThreads 4

open_project $proj_file

# Upgrade IPs locked from previous Vivado version
set locked [get_ips -filter {UPGRADE_VERSIONS != ""}]
if {[llength $locked] > 0} {
    puts "Upgrading [llength $locked] locked IP(s)..."
    upgrade_ip $locked
}

# Regenerate BD/IP output products before launching runs. The top-level synth
# consumes the OOC DCPs for module references such as hil_regs_0 and
# hil_axi_top_0; if these products are missing/stale, synth_1 can fail or link
# against an inconsistent checkpoint.
set bd_files [get_files -quiet -filter {FILE_TYPE == "Block Designs"}]
if {[llength $bd_files] > 0} {
    puts "Regenerating BD/IP output products..."
    generate_target all $bd_files
    export_ip_user_files -of_objects $bd_files -no_script -sync -force -quiet
}

set ooc_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}]
if {[llength $ooc_runs] > 0} {
    puts "Resetting [llength $ooc_runs] OOC synthesis run(s)..."
    foreach ooc_run $ooc_runs {
        reset_run $ooc_run
    }

    puts "Launching OOC synthesis run(s)..."
    launch_runs $ooc_runs -jobs 4
    foreach ooc_run $ooc_runs {
        wait_on_run $ooc_run
        if {[get_property PROGRESS [get_runs $ooc_run]] != "100%"} {
            error "OOC synthesis failed: $ooc_run"
        }
    }
}

# Síntese top-level. Os OOC DCPs acima já foram gerados e validados.
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY full [get_runs synth_1]
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "Síntese falhou"
}

# Implementação + bitstream
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "Implementação falhou"
}

# Exportar XSA
write_hw_platform -fixed -force -include_bit -file $xsa_out

puts ""
puts "============================================================"
puts " XSA exportado: $xsa_out"
puts "============================================================"
