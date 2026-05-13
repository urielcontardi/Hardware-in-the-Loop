##############################################################################
# upgrade_ip.tcl — Garante que BilienarSolverUnit_DSP usa DSP48E1
#
# Vivado 2025.1 gera C_MULT_TYPE=0 (MULT_AND/LUT) para "Use_Mults".
# Este script força C_MULT_TYPE=1 (DSP48E1) no XCI e regenera o IP.
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

# Escrever script Python ANTES do if (evita bug TCL: { em strings dentro de if{})
set dsp_ip [get_ips BilienarSolverUnit_DSP]
set xci_path ""
if {[llength $dsp_ip] > 0} {
    set xci_path [lindex [get_files BilienarSolverUnit_DSP.xci] 0]
}
set pyscript "/tmp/patch_mult_type.py"
set pyfd [open $pyscript w]
puts $pyfd "path = r'$xci_path'"
puts $pyfd {with open(path) as f:}
puts $pyfd {    txt = f.read()}
puts $pyfd "old = '\"C_MULT_TYPE\": \[ { \"value\": \"0\"'"
puts $pyfd "new = '\"C_MULT_TYPE\": \[ { \"value\": \"1\"'"
puts $pyfd {txt = txt.replace(old, new)}
puts $pyfd {with open(path, 'w') as f:}
puts $pyfd {    f.write(txt)}
close $pyfd

# Verificar e corrigir C_MULT_TYPE do DSP IP
if {[llength $dsp_ip] > 0} {
    set mc   [get_property CONFIG.Multiplier_Construction $dsp_ip]
    set cmt  [get_property CONFIG.C_MULT_TYPE $dsp_ip]
    puts "Multiplier_Construction: $mc  |  C_MULT_TYPE: $cmt"

    if {$cmt ne "1"} {
        puts "→ C_MULT_TYPE=$cmt (MULT_AND). Corrigindo para 1 (DSP48E1)..."
        exec python3 /tmp/patch_mult_type.py
        puts "→ XCI atualizado."
    } else {
        puts "→ C_MULT_TYPE=1 (DSP48E1) — já correto."
    }

    puts "→ Regenerando targets e resetando run OOC..."
    generate_target all $dsp_ip
    reset_run BilienarSolverUnit_DSP_synth_1

    # Limpar DCP para forçar nova síntese OOC
    set dsp_run_dir [get_property DIRECTORY [get_runs BilienarSolverUnit_DSP_synth_1]]
    foreach f [list \
        [file join $dsp_run_dir "BilienarSolverUnit_DSP.dcp"] \
        [file join $dsp_run_dir "__synthesis_is_complete__"] \
    ] {
        if {[file exists $f]} { file delete $f }
    }
    puts "→ Pronto. Execute resynth.tcl para síntese completa."
}

close_project
puts "Concluído."
