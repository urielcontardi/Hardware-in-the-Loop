##############################################################################
# resynth.tcl — Reset e re-run completo de synthesis + implementation
#
# Uso:
#   vivado -mode batch -source syn/hil/resynth.tcl
##############################################################################

set project_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]

puts "\n=== Atualizando Block Design (HIL_Regs_AXI) ===\n"
set bd_update [file normalize [file join [file dirname [info script]] bd_update.tcl]]
exec /opt/Xilinx/2025.1/Vivado/bin/vivado -mode batch \
    -source $bd_update \
    -log    [file join [file dirname [info script]] bd_update.log] \
    -journal [file join [file dirname [info script]] bd_update.jou] >@stdout 2>@stderr
puts "✓ Block Design atualizado\n"

puts "\n=== Abrindo projeto para síntese ===\n"
open_project -quiet $project_file

# ── 1. Resetar todos os runs OOC e principais ────────────────────────────
foreach run [list \
    "BilienarSolverUnit_DSP_synth_1" \
    "ebaz4205_hil_axi_top_0_0_synth_1" \
    "synth_1" \
    "impl_1" \
] {
    if {[llength [get_runs $run]] > 0} {
        puts "→ Resetando: $run"
        reset_run $run
    }
}

# ── 2. Limpar cache do DSP IP e forçar re-síntese com Use_Mults ──────────
# O Vivado reutiliza cache mesmo após mudança de Use_LUTs → Use_Mults.
# Deletar o .dcp e o marcador de conclusão força nova síntese do IP.
set dsp_run_dir [get_property DIRECTORY [get_runs BilienarSolverUnit_DSP_synth_1]]
set dsp_dcp     [file join $dsp_run_dir "BilienarSolverUnit_DSP.dcp"]
set dsp_done    [file join $dsp_run_dir "__synthesis_is_complete__"]
foreach f [list $dsp_dcp $dsp_done] {
    if {[file exists $f]} {
        file delete $f
        puts "→ Cache DSP removido: $f"
    }
}
# Regenerar targets do IP para garantir consistência
set dsp_ip [get_ips BilienarSolverUnit_DSP]
generate_target all $dsp_ip
puts "→ DSP IP targets regenerados (Use_Mults=[get_property CONFIG.Multiplier_Construction $dsp_ip])"

# ── 3. Rodar DSP OOC primeiro (Use_Mults) ────────────────────────────────
puts "\n=== Rodando DSP OOC synthesis (Use_Mults) ===\n"
launch_runs BilienarSolverUnit_DSP_synth_1 -jobs 4
wait_on_run BilienarSolverUnit_DSP_synth_1
set s [get_property STATUS [get_runs BilienarSolverUnit_DSP_synth_1]]
puts "DSP OOC status: $s"

# ── 4. Rodar HIL_AXI_Top OOC (nome pode variar após recriação do BD) ─────
puts "\n=== Rodando HIL_AXI_Top OOC synthesis ===\n"
set hil_ooc [lsearch -inline [get_runs] *hil_axi_top*synth*]
if {$hil_ooc ne ""} {
    reset_run $hil_ooc
    launch_runs $hil_ooc -jobs 4
    wait_on_run $hil_ooc
    puts "HIL OOC status: [get_property STATUS [get_runs $hil_ooc]]"
} else {
    puts "AVISO: run HIL OOC não encontrado — synth_1 irá triggerar automaticamente"
}

# ── 5. Rodar synthesis principal ─────────────────────────────────────────
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
