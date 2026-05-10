# =============================================================================
# run_impl.tcl
#
# Abre o projeto ebaz4205 já criado e executa:
#   síntese → implementação → bitstream
#
# Uso:
#   cd <repo>/syn/hil
#   vivado -mode batch -source run_impl.tcl
# =============================================================================

set_param general.maxThreads 4

set script_dir "[file normalize [file dirname [info script]]]"
set proj_file  "$script_dir/ebaz4205/ebaz4205.xpr"

if {![file exists $proj_file]} {
    puts "ERRO: projeto não encontrado em $proj_file"
    puts "Execute primeiro: vivado -mode batch -source create_ebaz4205_project.tcl"
    exit 1
}

open_project $proj_file

# Regenerate BD/IP output products and complete OOC synthesis before synth_1.
# The block-design top consumes DCPs for module references and IPs; launching
# synth_1 before those DCPs exist can leave the wrapper linked against stale or
# missing hardware.
set bd_files [get_files -quiet -filter {FILE_TYPE == "Block Designs"}]
if {[llength $bd_files] > 0} {
    puts "Regenerando produtos BD/IP..."
    generate_target all $bd_files
    export_ip_user_files -of_objects $bd_files -no_script -sync -force -quiet
}

set ooc_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}]
if {[llength $ooc_runs] > 0} {
    puts "Resetando [llength $ooc_runs] run(s) OOC..."
    foreach ooc_run $ooc_runs {
        reset_run $ooc_run
    }

    puts "Rodando sintese OOC..."
    launch_runs $ooc_runs -jobs 4
    foreach ooc_run $ooc_runs {
        wait_on_run $ooc_run
        if {[get_property PROGRESS [get_runs $ooc_run]] != "100%"} {
            puts "ERRO: sintese OOC falhou: $ooc_run"
            exit 1
        }
    }
}

# =============================================================================
# Síntese
# =============================================================================
puts ""
puts "=== \[1/3\] Síntese ==="
reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "ERRO: síntese falhou."
    exit 1
}
puts "  Síntese concluída."

# =============================================================================
# Implementação
# =============================================================================
puts ""
puts "=== \[2/3\] Implementação ==="
reset_run impl_1
launch_runs impl_1 -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "ERRO: implementação falhou."
    exit 1
}
puts "  Implementação concluída."

# =============================================================================
# Bitstream
# =============================================================================
puts ""
puts "=== \[3/3\] Gerando bitstream ==="
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
puts "  Bitstream gerado."

set bit_file [glob -nocomplain "$script_dir/ebaz4205/ebaz4205.runs/impl_1/*.bit"]
puts ""
puts "============================================================"
puts " Bitstream: $bit_file"
puts "============================================================"
