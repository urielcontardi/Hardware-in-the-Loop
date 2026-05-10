##############################################################################
# bd_update.tcl — Recria o Block Design do zero com HIL_Regs_AXI + sem DMA
##############################################################################

set proj_file [file normalize [file join [file dirname [info script]] \
    ebaz4205/ebaz4205.xpr]]
set rtl_dir [file normalize [file join [file dirname [info script]] \
    ../../src/rtl]]

open_project -quiet $proj_file

# Garantir que HIL_Regs_AXI.vhd está no projeto
set regs_vhd [file join $rtl_dir HIL_Regs_AXI.vhd]
if {[llength [get_files $regs_vhd]] == 0} {
    add_files -fileset sources_1 -norecurse $regs_vhd
}
update_compile_order -fileset sources_1

# ── Deletar e recriar o Block Design ─────────────────────────────────────
puts "→ Deletando BD existente e recriando do zero..."
set bd_file [get_files -of_objects [get_filesets sources_1] \
    -filter {FILE_TYPE == "Block Designs"} -quiet]
if {$bd_file ne ""} {
    # Fechar se aberto
    catch { close_bd_design [current_bd_design] }
    # Remover do projeto
    remove_files -fileset sources_1 $bd_file
    # Deletar arquivo
    file delete $bd_file
}

# Criar novo BD
create_bd_design "ebaz4205"
current_bd_design "ebaz4205"

# ── PS7 ──────────────────────────────────────────────────────────────────
set ps [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0       {1} \
    CONFIG.PCW_USE_S_AXI_HP0       {0} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {150} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR        {1} \
    CONFIG.PCW_EN_CLK0_PORT        {1} \
    CONFIG.PCW_EN_RST0_PORT        {1} \
] $ps
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR"} $ps

# ── proc_sys_reset ───────────────────────────────────────────────────────
set psr [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0]

# ── HIL_Regs_AXI — custom slave (PS→PL data path) ───────────────────────
set hil_regs [create_bd_cell -type module \
    -reference HIL_Regs_AXI hil_regs_0]

# ── HIL_AXI_Top ──────────────────────────────────────────────────────────
set hil_top [create_bd_cell -type module \
    -reference HIL_AXI_Top hil_axi_top_0]

# ── AXI GPIO : monitor 1 — correntes ─────────────────────────────────────
set gpio_mon1 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_monitor_1]
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH   {32} CONFIG.C_GPIO2_WIDTH  {32} \
    CONFIG.C_IS_DUAL      {1}  CONFIG.C_ALL_INPUTS   {1} \
    CONFIG.C_ALL_INPUTS_2 {1}] $gpio_mon1

# ── AXI GPIO : monitor 2 — fluxos ────────────────────────────────────────
set gpio_mon2 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_monitor_2]
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH   {32} CONFIG.C_GPIO2_WIDTH  {32} \
    CONFIG.C_IS_DUAL      {1}  CONFIG.C_ALL_INPUTS   {1} \
    CONFIG.C_ALL_INPUTS_2 {1}] $gpio_mon2

# ── AXI GPIO : monitor 3 — velocidade + data_valid ───────────────────────
set gpio_mon3 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_monitor_3]
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH   {32} CONFIG.C_GPIO2_WIDTH  {1} \
    CONFIG.C_IS_DUAL      {1}  CONFIG.C_ALL_INPUTS   {1} \
    CONFIG.C_ALL_INPUTS_2 {1}] $gpio_mon3

# ── AXI SmartConnect : GP0 → 4 slaves ────────────────────────────────────
set sc0 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:smartconnect:1.0 axi_smartconnect_0]
set_property CONFIG.NUM_MI {4} $sc0

# ── Clocks ────────────────────────────────────────────────────────────────
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_pins proc_sys_reset_0/slowest_sync_clk] \
    [get_bd_pins axi_smartconnect_0/aclk] \
    [get_bd_pins hil_regs_0/S_AXI_ACLK] \
    [get_bd_pins axi_gpio_monitor_1/s_axi_aclk] \
    [get_bd_pins axi_gpio_monitor_2/s_axi_aclk] \
    [get_bd_pins axi_gpio_monitor_3/s_axi_aclk] \
    [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
    [get_bd_pins hil_axi_top_0/clk]

# ── Resets ────────────────────────────────────────────────────────────────
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
    [get_bd_pins proc_sys_reset_0/ext_reset_in]
connect_bd_net \
    [get_bd_pins proc_sys_reset_0/interconnect_aresetn] \
    [get_bd_pins axi_smartconnect_0/aresetn]
connect_bd_net \
    [get_bd_pins proc_sys_reset_0/peripheral_aresetn] \
    [get_bd_pins hil_regs_0/S_AXI_ARESETN] \
    [get_bd_pins axi_gpio_monitor_1/s_axi_aresetn] \
    [get_bd_pins axi_gpio_monitor_2/s_axi_aresetn] \
    [get_bd_pins axi_gpio_monitor_3/s_axi_aresetn] \
    [get_bd_pins hil_axi_top_0/rst_n]

# ── AXI interfaces ────────────────────────────────────────────────────────
connect_bd_intf_net \
    [get_bd_intf_pins processing_system7_0/M_AXI_GP0] \
    [get_bd_intf_pins axi_smartconnect_0/S00_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_smartconnect_0/M00_AXI] \
    [get_bd_intf_pins hil_regs_0/S_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_smartconnect_0/M01_AXI] \
    [get_bd_intf_pins axi_gpio_monitor_1/S_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_smartconnect_0/M02_AXI] \
    [get_bd_intf_pins axi_gpio_monitor_2/S_AXI]
connect_bd_intf_net \
    [get_bd_intf_pins axi_smartconnect_0/M03_AXI] \
    [get_bd_intf_pins axi_gpio_monitor_3/S_AXI]

# ── HIL_Regs → HIL_AXI_Top ───────────────────────────────────────────────
connect_bd_net [get_bd_pins hil_regs_0/va_ref_o]      [get_bd_pins hil_axi_top_0/va_ref_i]
connect_bd_net [get_bd_pins hil_regs_0/vb_ref_o]      [get_bd_pins hil_axi_top_0/vb_ref_i]
connect_bd_net [get_bd_pins hil_regs_0/vc_ref_o]      [get_bd_pins hil_axi_top_0/vc_ref_i]
connect_bd_net [get_bd_pins hil_regs_0/pwm_ctrl_o]    [get_bd_pins hil_axi_top_0/pwm_ctrl_i]
connect_bd_net [get_bd_pins hil_regs_0/vdc_word_o]    [get_bd_pins hil_axi_top_0/vdc_word_i]
connect_bd_net [get_bd_pins hil_regs_0/torque_word_o] [get_bd_pins hil_axi_top_0/torque_word_i]
connect_bd_net [get_bd_pins hil_axi_top_0/ialpha_mon_o] [get_bd_pins hil_regs_0/debug0_i]

# ── HIL_AXI_Top → monitors ───────────────────────────────────────────────
connect_bd_net [get_bd_pins hil_axi_top_0/ialpha_mon_o]     [get_bd_pins axi_gpio_monitor_1/gpio_io_i]
connect_bd_net [get_bd_pins hil_axi_top_0/ibeta_mon_o]      [get_bd_pins axi_gpio_monitor_1/gpio2_io_i]
connect_bd_net [get_bd_pins hil_axi_top_0/flux_alpha_mon_o] [get_bd_pins axi_gpio_monitor_2/gpio_io_i]
connect_bd_net [get_bd_pins hil_axi_top_0/flux_beta_mon_o]  [get_bd_pins axi_gpio_monitor_2/gpio2_io_i]
connect_bd_net [get_bd_pins hil_axi_top_0/speed_mon_o]      [get_bd_pins axi_gpio_monitor_3/gpio_io_i]
connect_bd_net [get_bd_pins hil_axi_top_0/data_valid_mon_o] [get_bd_pins axi_gpio_monitor_3/gpio2_io_i]

# ── IRQ ───────────────────────────────────────────────────────────────────
connect_bd_net \
    [get_bd_pins hil_axi_top_0/carrier_tick_o] \
    [get_bd_pins processing_system7_0/IRQ_F2P]

# ── Endereços ─────────────────────────────────────────────────────────────
assign_bd_address
if {[llength [get_bd_addr_segs \
        {processing_system7_0/Data/SEG_hil_regs_0_reg0}]] > 0} {
    set_property offset 0x43C00000 \
        [get_bd_addr_segs {processing_system7_0/Data/SEG_hil_regs_0_reg0}]
    set_property range 4K \
        [get_bd_addr_segs {processing_system7_0/Data/SEG_hil_regs_0_reg0}]
    puts "→ HIL_Regs: 0x43C00000"
}

# ── Gerar wrapper e salvar ────────────────────────────────────────────────
validate_bd_design
save_bd_design

# Gerar wrapper HDL
set wrapper [make_wrapper -files [get_files ebaz4205.bd] -top]
add_files -norecurse $wrapper
update_compile_order -fileset sources_1
set_property top ebaz4205_wrapper [current_fileset]

close_bd_design [current_bd_design]
close_project
puts "\n✓ Block Design recriado com HIL_Regs_AXI (sem DMA)"
