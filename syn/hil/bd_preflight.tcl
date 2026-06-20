# Canonical block-design contract checks shared by validation and synthesis.
proc hil_bd_preflight {} {
    set bd [lindex [get_files -quiet -filter {FILE_TYPE == "Block Designs"}] 0]
    if {$bd eq ""} {
        error "Block design not found; run make vivado-project"
    }
    open_bd_design $bd

    set required_connected_pins [list \
        hil_axi_top_0/pwm_cap_start_i hil_axi_top_0/pwm_cap_stop_i \
        hil_axi_top_0/pwm_cap_clear_i hil_axi_top_0/pwm_cap_pop_i \
        hil_axi_top_0/pwm_cap_window_i hil_regs_0/pwm_cap_status_i \
        hil_regs_0/pwm_cap_data_i hil_regs_0/hil_time_i hil_regs_0/hil_epoch_i]
    foreach pin_name $required_connected_pins {
        set pin [get_bd_pins -quiet $pin_name]
        if {[llength $pin] == 0 || [llength [get_bd_nets -quiet -of_objects $pin]] == 0} {
            error "Stale block design: $pin_name is disconnected"
        }
    }

    validate_bd_design
    puts "Block-design preflight PASS: HIL timeline and PWM capture links connected"
}
