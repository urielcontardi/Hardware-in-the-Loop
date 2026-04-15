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

# Síntese
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "Síntese falhou"
}

# Implementação + bitstream
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
