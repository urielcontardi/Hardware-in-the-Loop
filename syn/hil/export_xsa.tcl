##############################################################################
# export_xsa.tcl — Exporta XSA do impl_1 já completo (sem re-sintetizar)
##############################################################################

set proj_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]
set xsa_out   [file normalize [file join [file dirname [info script]] \
    ebaz4205.xsa]]

open_project -quiet $proj_file

# Verificar que impl está completo
set status [get_property STATUS [get_runs impl_1]]
puts "impl_1 status: $status"

if {![string match "*write_bitstream Complete*" $status]} {
    puts "ERRO: impl_1 não está completo. Rode resynth.tcl primeiro."
    close_project
    exit 1
}

# Abrir checkpoint do impl para exportar
open_run impl_1

# Exportar XSA com bitstream incluído
write_hw_platform -fixed -force -include_bit -file $xsa_out

puts ""
puts "✓ XSA exportado: $xsa_out"
puts "  Tamanho: [file size $xsa_out] bytes"

close_project
puts "Concluído."
