##############################################################################
# upgrade_ip.tcl — Regenera o DSP IP após mudança de Use_LUTs → Use_Mults
##############################################################################

set proj_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]

open_project -quiet $proj_file

# Upgrade todos os IPs travados
set locked [get_ips -filter {UPGRADE_VERSIONS != "" || IS_LOCKED == "1"}]
if {[llength $locked] > 0} {
    puts "Upgrading [llength $locked] locked IP(s): $locked"
    upgrade_ip $locked
}

# Forçar regeneração do DSP IP
set dsp_ip [get_ips BilienarSolverUnit_DSP]
if {[llength $dsp_ip] > 0} {
    puts "Regenerando DSP IP..."
    generate_target all $dsp_ip
    reset_run BilienarSolverUnit_DSP_synth_1
}

# Verificar configuração
set mc [get_property CONFIG.Multiplier_Construction $dsp_ip]
puts "Multiplier_Construction: $mc"

close_project
puts "Concluído."
