##############################################################################
# resynth.tcl — Reset e re-run completo de synthesis + implementation
#
# Uso:
#   vivado -mode batch -source syn/hil/resynth.tcl
##############################################################################

set project_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]

# NOTA: resynth.tcl NÃO recria o Block Design.
# O BD completo (com EMIO Ethernet, GMII, MDIO, xlconcat/xlslice, etc.)
# é criado apenas por create_ebaz4205_project.tcl via 'make vivado-project'.
# bd_update.tcl estava incompleto (sem EMIO Ethernet) e causava bitstream quebrado.
puts "\n=== Abrindo projeto para síntese ===\n"
open_project -quiet $project_file

# ── 1. Garantir que IP BilienarSolverUnit_DSP usa DSP48E1 (C_MULT_TYPE=1) ──
# NOTA: A escrita do script Python é feita FORA de blocos if {} para evitar
# o bug do TCL: { dentro de strings double-quoted dentro de if {} são
# contados no balanceamento de chaves, causando "missing close-brace".
set dsp_ip [get_ips -quiet BilienarSolverUnit_DSP]
set xci_path ""
if {[llength $dsp_ip] > 0} {
    set xci_path [lindex [get_files BilienarSolverUnit_DSP.xci] 0]
}

# Escrever script Python no nível global (sem if aninhado)
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

if {[llength $dsp_ip] > 0} {
    set cmt [get_property CONFIG.C_MULT_TYPE $dsp_ip]
    puts "→ BilienarSolverUnit_DSP: C_MULT_TYPE=$cmt, Locked=[get_property IS_LOCKED $dsp_ip]"
    if {$cmt ne "1"} {
        puts "→ Corrigindo C_MULT_TYPE para 1 (DSP48E1)..."
        exec python3 $pyscript
    }
    generate_target all $dsp_ip -quiet
}

# Limpar DCP e cache do run DSP OOC (só se o run já existir)
set dsp_runs [get_runs -quiet BilienarSolverUnit_DSP_synth_1]
if {[llength $dsp_runs] > 0} {
    set dsp_run_dir [get_property DIRECTORY $dsp_runs]
    foreach f [list \
        [file join $dsp_run_dir "BilienarSolverUnit_DSP.dcp"] \
        [file join $dsp_run_dir "__synthesis_is_complete__"] \
    ] {
        if {[file exists $f]} { file delete $f; puts "→ Cache removido: [file tail $f]" }
    }
}

# ── 2. Resetar todos os runs (apenas os que existem) ─────────────────────
foreach run [list \
    "BilienarSolverUnit_DSP_synth_1" \
    "ebaz4205_hil_axi_top_0_0_synth_1" \
    "synth_1" \
    "impl_1" \
] {
    if {[llength [get_runs -quiet $run]] > 0} {
        puts "→ Resetando: $run"
        reset_run $run
    }
}
# ── 3. Rodar synthesis principal (OOC hil_axi_top é triggrado automaticamente) ─
puts "\n=== Iniciando synthesis top-level (jobs=4) ===\n"
launch_runs synth_1 -jobs 4
wait_on_run synth_1

set synth_status [get_property STATUS [get_runs synth_1]]
puts "\nSynthesis status: $synth_status"
if {[string match "*error*" [string tolower $synth_status]]} {
    puts "ERRO na synthesis — abortando."
    close_project
    exit 1
}

# ── 6. Rodar implementation + write_bitstream ─────────────────────────────
puts "\n=== Iniciando implementation + write_bitstream (jobs=4) ===\n"
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
puts "\nImplementation status: $impl_status"

# ── 7. Confirmar bitstream gerado ─────────────────────────────────────────
set bit_file [file join [get_property DIRECTORY [get_runs impl_1]] \
    ebaz4205_wrapper.bit]
if {[file exists $bit_file]} {
    puts "\n✓ Bitstream gerado: $bit_file"
    puts "  Tamanho: [file size $bit_file] bytes"
    puts "  Data:    [clock format [file mtime $bit_file] -format {%Y-%m-%d %H:%M}]"
} else {
    puts "\n✗ Bitstream NÃO encontrado em: $bit_file"
}

close_project

# ── 8. Converter .bit → .bin via bootgen (sem header Xilinx) ─────────────
# fpgautil no PetaLinux aceita apenas .bin
if {[file exists $bit_file]} {
    set bin_file "${bit_file}.bin"
    set bif_file "/tmp/ebaz4205_resynth.bif"
    set fd [open $bif_file w]
    puts $fd "all:"
    puts $fd "{"
    puts $fd "  $bit_file"
    puts $fd "}"
    close $fd

    if {[catch {
        exec bootgen -image $bif_file -arch zynq \
             -process_bitstream bin -o $bin_file -w 2>@1
    } msg]} {
        puts "\n✗ bootgen falhou: $msg"
    } else {
        puts "✓ BIN gerado: $bin_file"
    }
    file delete $bif_file
}

puts "\nConcluído."
