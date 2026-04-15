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

# =============================================================================
# Síntese
# =============================================================================
puts ""
puts "=== \[1/3\] Síntese ==="
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
