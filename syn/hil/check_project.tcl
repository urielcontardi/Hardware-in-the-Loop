set script_dir [file normalize [file dirname [info script]]]
set proj_file  [file join $script_dir ebaz4205 ebaz4205.xpr]
open_project $proj_file
source [file join $script_dir bd_preflight.tcl]
hil_bd_preflight
close_project
