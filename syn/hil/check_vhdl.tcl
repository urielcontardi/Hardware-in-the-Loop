##############################################################################
# check_vhdl.tcl — Validação rápida de sintaxe (sem rodar synthesis completa)
#
# Uso:
#   vivado -mode batch -source syn/hil/check_vhdl.tcl
##############################################################################

set project_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]

open_project -quiet $project_file

# Atualiza as fontes RTL no projeto (caso tenham sido alteradas)
update_compile_order -fileset sources_1

# Checa sintaxe SEM rodar synthesis
set check_result [check_syntax -fileset sources_1 -return_string]
puts $check_result

puts "\nSyntax check concluído."

close_project
