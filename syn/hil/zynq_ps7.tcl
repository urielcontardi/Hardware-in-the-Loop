# =============================================================================
# zynq_ps7.tcl
# Block Design: PS7 + AXI GPIO for voltage references
#
#   PS (ARM) writes va_ref / vb_ref / vc_ref / pwm_ctrl via M_AXI_GP0.
#   PL receives them as 32-bit output ports from the wrapper.
#
#   Address map (PS data space):
#     0x41200000  axi_gpio_0  ch1=va_ref  ch2=vb_ref
#     0x41210000  axi_gpio_1  ch1=vc_ref  ch2=pwm_ctrl
#
# NOTE: DDR timing parameters are set to generic defaults.
#       If PS will run Linux, configure DDR precisely via Vivado GUI.
# =============================================================================

create_bd_design "zynq_ps7"

# -----------------------------------------------------------------------------
# Processing System 7
# -----------------------------------------------------------------------------
set ps7 [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:processing_system7:5.5 \
    processing_system7_0]

set_property -dict [list \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ  {150}  \
    CONFIG.PCW_EN_CLK0_PORT              {1}    \
    CONFIG.PCW_EN_RST0_PORT              {1}    \
    CONFIG.PCW_USE_FABRIC_INTERRUPT      {0}    \
    CONFIG.PCW_UART0_PERIPHERAL_ENABLE   {0}    \
    CONFIG.PCW_USE_M_AXI_GP0             {1}    \
    CONFIG.PCW_UIPARAM_DDR_MEMORY_TYPE   {DDR 3}\
    CONFIG.PCW_DDR_RAM_HIGHADDR          {0x1FFFFFFF} \
] $ps7

# Connect DDR and FIXED_IO (PS-side, board-level pins)
apply_bd_automation \
    -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} \
    $ps7

# M_AXI_GP0 clock must be driven by FCLK_CLK0
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK]

# -----------------------------------------------------------------------------
# Reset controller: FCLK_RESET0_N → peripheral_aresetn
# -----------------------------------------------------------------------------
set rst [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:proc_sys_reset:5.0 \
    rst_0]

connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_pins rst_0/slowest_sync_clk]
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
    [get_bd_pins rst_0/ext_reset_in]

# -----------------------------------------------------------------------------
# AXI Interconnect: 1 master (GP0), 2 slaves (gpio_0, gpio_1)
# -----------------------------------------------------------------------------
set ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 \
    axi_ic]
set_property -dict [list \
    CONFIG.NUM_SI {1} \
    CONFIG.NUM_MI {2} \
] $ic

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_ic/ACLK]
connect_bd_net [get_bd_pins rst_0/interconnect_aresetn] \
               [get_bd_pins axi_ic/ARESETN]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_ic/S00_ACLK]
connect_bd_net [get_bd_pins rst_0/peripheral_aresetn] \
               [get_bd_pins axi_ic/S00_ARESETN]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_ic/M00_ACLK]
connect_bd_net [get_bd_pins rst_0/peripheral_aresetn] \
               [get_bd_pins axi_ic/M00_ARESETN]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_ic/M01_ACLK]
connect_bd_net [get_bd_pins rst_0/peripheral_aresetn] \
               [get_bd_pins axi_ic/M01_ARESETN]

connect_bd_intf_net \
    [get_bd_intf_pins processing_system7_0/M_AXI_GP0] \
    [get_bd_intf_pins axi_ic/S00_AXI]

# -----------------------------------------------------------------------------
# AXI GPIO 0: ch1 = va_ref (32-bit), ch2 = vb_ref (32-bit)
# -----------------------------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH    {32} \
    CONFIG.C_GPIO2_WIDTH   {32} \
    CONFIG.C_IS_DUAL       {1}  \
    CONFIG.C_ALL_OUTPUTS   {1}  \
    CONFIG.C_ALL_OUTPUTS_2 {1}  \
] [get_bd_cells axi_gpio_0]

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_gpio_0/s_axi_aclk]
connect_bd_net [get_bd_pins rst_0/peripheral_aresetn] \
               [get_bd_pins axi_gpio_0/s_axi_aresetn]
connect_bd_intf_net \
    [get_bd_intf_pins axi_ic/M00_AXI] \
    [get_bd_intf_pins axi_gpio_0/S_AXI]

# -----------------------------------------------------------------------------
# AXI GPIO 1: ch1 = vc_ref (32-bit), ch2 = pwm_ctrl (32-bit)
# -----------------------------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_1
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH    {32} \
    CONFIG.C_GPIO2_WIDTH   {32} \
    CONFIG.C_IS_DUAL       {1}  \
    CONFIG.C_ALL_OUTPUTS   {1}  \
    CONFIG.C_ALL_OUTPUTS_2 {1}  \
] [get_bd_cells axi_gpio_1]

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
               [get_bd_pins axi_gpio_1/s_axi_aclk]
connect_bd_net [get_bd_pins rst_0/peripheral_aresetn] \
               [get_bd_pins axi_gpio_1/s_axi_aresetn]
connect_bd_intf_net \
    [get_bd_intf_pins axi_ic/M01_AXI] \
    [get_bd_intf_pins axi_gpio_1/S_AXI]

# -----------------------------------------------------------------------------
# Address assignment
# -----------------------------------------------------------------------------
assign_bd_address [get_bd_addr_segs axi_gpio_0/S_AXI/Reg]
set_property offset 0x41200000 \
    [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_0_Reg}]
set_property range 64K \
    [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_0_Reg}]

assign_bd_address [get_bd_addr_segs axi_gpio_1/S_AXI/Reg]
set_property offset 0x41210000 \
    [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_1_Reg}]
set_property range 64K \
    [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_1_Reg}]

# -----------------------------------------------------------------------------
# Expose FCLK_CLK0 and FCLK_RESET0_N as BD output ports
# -----------------------------------------------------------------------------
create_bd_port -dir O -type clk fclk_clk0
set_property CONFIG.FREQ_HZ 200000000 [get_bd_ports fclk_clk0]
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_ports fclk_clk0]

create_bd_port -dir O -type rst fclk_reset_n
connect_bd_net \
    [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
    [get_bd_ports fclk_reset_n]

# -----------------------------------------------------------------------------
# Expose GPIO outputs as BD ports
# (wrapper will have: va_ref, vb_ref, vc_ref, pwm_ctrl — all 32-bit outputs)
# -----------------------------------------------------------------------------
create_bd_port -dir O -from 31 -to 0 va_ref
connect_bd_net [get_bd_pins axi_gpio_0/gpio_io_o]  [get_bd_ports va_ref]

create_bd_port -dir O -from 31 -to 0 vb_ref
connect_bd_net [get_bd_pins axi_gpio_0/gpio2_io_o] [get_bd_ports vb_ref]

create_bd_port -dir O -from 31 -to 0 vc_ref
connect_bd_net [get_bd_pins axi_gpio_1/gpio_io_o]  [get_bd_ports vc_ref]

create_bd_port -dir O -from 31 -to 0 pwm_ctrl
connect_bd_net [get_bd_pins axi_gpio_1/gpio2_io_o] [get_bd_ports pwm_ctrl]

# -----------------------------------------------------------------------------
# Validate and save
# -----------------------------------------------------------------------------
validate_bd_design
save_bd_design
generate_target all [get_files zynq_ps7.bd]

puts "Block design 'zynq_ps7' created (FCLK=200MHz, AXI GPIO: va/vb/vc_ref + pwm_ctrl)."
