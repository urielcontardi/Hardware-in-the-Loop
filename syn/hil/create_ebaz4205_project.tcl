# =============================================================================
# create_ebaz4205_project.tcl
#
# Recria o projeto Vivado 2025.1 para a EBAZ4205 (Zynq-7010),
# replicando exatamente o que o ebaz4205.tcl original (2021.2) fazia:
#   - PS7 completo (FCLK0=50MHz, FCLK3=25MHz, ENET0 EMIO, MDIO EMIO,
#                   DDR3, SD0, UART1, NAND)
#   - xlconcat_0 : agrega RXD[3:0] + RXD[7:4] → ENET0_GMII_RXD[7:0]
#   - xlslice_0  : fatia TXD[7:0] → enet0_gmii_txd[3:0]
#   - xlslice_1  : fatia GPIO_O[1:0] → LED[1:0]
#
# Uso (Vivado Tcl Console ou batch):
#   cd <repo>/syn/hil
#   source create_ebaz4205_project.tcl
# =============================================================================

set proj_name  "ebaz4205"
set proj_dir   "[file normalize [file join [file dirname [info script]] $proj_name]]"
set script_dir "[file normalize [file dirname [info script]]]"
set part       "xc7z010clg400-1"
set xdc_file   "$script_dir/ebaz4205_board.xdc"

# =============================================================================
# 1. Criar projeto
# =============================================================================
create_project $proj_name $proj_dir -part $part -force

set obj [current_project]
set_property default_lib        xil_defaultlib $obj
set_property enable_vhdl_2008   1              $obj
set_property simulator_language Mixed          $obj

# =============================================================================
# 2. Block Design "ebaz4205"
# =============================================================================
proc cr_bd_ebaz4205 {} {

    create_bd_design "ebaz4205"
    current_bd_instance [get_bd_cells /]

    # ── Interface ports ────────────────────────────────────────────────────────
    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0           DDR
    create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO
    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:mdio_rtl:1.0           MDIO_ETHERNET_0_0

    # ── Portas externas ────────────────────────────────────────────────────────
    create_bd_port -dir I -type clk ENET0_GMII_RX_CLK_0
    create_bd_port -dir I           ENET0_GMII_RX_DV_0
    create_bd_port -dir I -type clk ENET0_GMII_TX_CLK_0
    create_bd_port -dir O -from 0 -to 0 ENET0_GMII_TX_EN_0
    set fclk3 [create_bd_port -dir O -type clk FCLK_CLK3_0]
    set_property CONFIG.FREQ_HZ {25000000} $fclk3
    create_bd_port -dir O -from 1 -to 0 LED
    create_bd_port -dir I -from 3 -to 0 enet0_gmii_rxd
    create_bd_port -dir O -from 3 -to 0 enet0_gmii_txd

    # ── PS7 ────────────────────────────────────────────────────────────────────
    set ps7 [create_bd_cell -type ip \
                 -vlnv xilinx.com:ip:processing_system7:5.5 \
                 processing_system7_0]

    set_property -dict [list \
        CONFIG.PCW_ACT_APU_PERIPHERAL_FREQMHZ    {666.666687} \
        CONFIG.PCW_ACT_CAN_PERIPHERAL_FREQMHZ    {10.000000} \
        CONFIG.PCW_ACT_DCI_PERIPHERAL_FREQMHZ    {10.158730} \
        CONFIG.PCW_ACT_ENET0_PERIPHERAL_FREQMHZ  {25.000000} \
        CONFIG.PCW_ACT_ENET1_PERIPHERAL_FREQMHZ  {10.000000} \
        CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ  {50.000000} \
        CONFIG.PCW_ACT_FPGA1_PERIPHERAL_FREQMHZ  {10.000000} \
        CONFIG.PCW_ACT_FPGA2_PERIPHERAL_FREQMHZ  {10.000000} \
        CONFIG.PCW_ACT_FPGA3_PERIPHERAL_FREQMHZ  {25.000000} \
        CONFIG.PCW_ACT_PCAP_PERIPHERAL_FREQMHZ   {200.000000} \
        CONFIG.PCW_ACT_QSPI_PERIPHERAL_FREQMHZ   {10.000000} \
        CONFIG.PCW_ACT_SDIO_PERIPHERAL_FREQMHZ   {25.000000} \
        CONFIG.PCW_ACT_SMC_PERIPHERAL_FREQMHZ    {100.000000} \
        CONFIG.PCW_ACT_SPI_PERIPHERAL_FREQMHZ    {10.000000} \
        CONFIG.PCW_ACT_TPIU_PERIPHERAL_FREQMHZ   {200.000000} \
        CONFIG.PCW_ACT_TTC0_CLK0_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_TTC0_CLK1_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_TTC0_CLK2_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_TTC1_CLK0_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_TTC1_CLK1_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_TTC1_CLK2_PERIPHERAL_FREQMHZ {111.111115} \
        CONFIG.PCW_ACT_UART_PERIPHERAL_FREQMHZ   {100.000000} \
        CONFIG.PCW_ACT_WDT_PERIPHERAL_FREQMHZ    {111.111115} \
        CONFIG.PCW_ARMPLL_CTRL_FBDIV             {40} \
        CONFIG.PCW_CAN_PERIPHERAL_DIVISOR0       {1} \
        CONFIG.PCW_CAN_PERIPHERAL_DIVISOR1       {1} \
        CONFIG.PCW_CLK0_FREQ   {50000000} \
        CONFIG.PCW_CLK1_FREQ   {10000000} \
        CONFIG.PCW_CLK2_FREQ   {10000000} \
        CONFIG.PCW_CLK3_FREQ   {25000000} \
        CONFIG.PCW_CPU_CPU_PLL_FREQMHZ           {1333.333} \
        CONFIG.PCW_CPU_PERIPHERAL_DIVISOR0       {2} \
        CONFIG.PCW_DCI_PERIPHERAL_DIVISOR0       {15} \
        CONFIG.PCW_DCI_PERIPHERAL_DIVISOR1       {7} \
        CONFIG.PCW_DDRPLL_CTRL_FBDIV             {32} \
        CONFIG.PCW_DDR_DDR_PLL_FREQMHZ           {1066.667} \
        CONFIG.PCW_DDR_PERIPHERAL_DIVISOR0       {2} \
        CONFIG.PCW_DDR_RAM_HIGHADDR              {0x0FFFFFFF} \
        CONFIG.PCW_ENET0_ENET0_IO                {EMIO} \
        CONFIG.PCW_ENET0_GRP_MDIO_ENABLE         {1} \
        CONFIG.PCW_ENET0_GRP_MDIO_IO             {EMIO} \
        CONFIG.PCW_ENET0_PERIPHERAL_CLKSRC       {External} \
        CONFIG.PCW_ENET0_PERIPHERAL_DIVISOR0     {1} \
        CONFIG.PCW_ENET0_PERIPHERAL_DIVISOR1     {5} \
        CONFIG.PCW_ENET0_PERIPHERAL_ENABLE       {1} \
        CONFIG.PCW_ENET0_PERIPHERAL_FREQMHZ      {100 Mbps} \
        CONFIG.PCW_ENET0_RESET_ENABLE            {0} \
        CONFIG.PCW_ENET1_PERIPHERAL_DIVISOR0     {1} \
        CONFIG.PCW_ENET1_PERIPHERAL_DIVISOR1     {1} \
        CONFIG.PCW_ENET1_RESET_ENABLE            {0} \
        CONFIG.PCW_ENET_RESET_ENABLE             {1} \
        CONFIG.PCW_ENET_RESET_SELECT             {Share reset pin} \
        CONFIG.PCW_EN_CLK3_PORT                  {1} \
        CONFIG.PCW_EN_EMIO_CD_SDIO0              {0} \
        CONFIG.PCW_EN_EMIO_ENET0                 {1} \
        CONFIG.PCW_EN_EMIO_GPIO                  {1} \
        CONFIG.PCW_EN_ENET0                      {1} \
        CONFIG.PCW_EN_GPIO                       {1} \
        CONFIG.PCW_EN_SDIO0                      {1} \
        CONFIG.PCW_EN_SMC                        {1} \
        CONFIG.PCW_EN_UART1                      {1} \
        CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR0     {7} \
        CONFIG.PCW_FCLK0_PERIPHERAL_DIVISOR1     {4} \
        CONFIG.PCW_FCLK1_PERIPHERAL_DIVISOR0     {1} \
        CONFIG.PCW_FCLK1_PERIPHERAL_DIVISOR1     {1} \
        CONFIG.PCW_FCLK2_PERIPHERAL_DIVISOR0     {1} \
        CONFIG.PCW_FCLK2_PERIPHERAL_DIVISOR1     {1} \
        CONFIG.PCW_FCLK3_PERIPHERAL_DIVISOR0     {8} \
        CONFIG.PCW_FCLK3_PERIPHERAL_DIVISOR1     {7} \
        CONFIG.PCW_FCLK_CLK3_BUF                 {TRUE} \
        CONFIG.PCW_FPGA3_PERIPHERAL_FREQMHZ      {25} \
        CONFIG.PCW_FPGA_FCLK0_ENABLE             {1} \
        CONFIG.PCW_FPGA_FCLK1_ENABLE             {0} \
        CONFIG.PCW_FPGA_FCLK2_ENABLE             {0} \
        CONFIG.PCW_FPGA_FCLK3_ENABLE             {1} \
        CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE         {1} \
        CONFIG.PCW_GPIO_EMIO_GPIO_IO             {64} \
        CONFIG.PCW_GPIO_EMIO_GPIO_WIDTH          {64} \
        CONFIG.PCW_GPIO_MIO_GPIO_ENABLE          {1} \
        CONFIG.PCW_GPIO_MIO_GPIO_IO              {MIO} \
        CONFIG.PCW_I2C0_RESET_ENABLE             {0} \
        CONFIG.PCW_I2C1_RESET_ENABLE             {0} \
        CONFIG.PCW_I2C_PERIPHERAL_FREQMHZ        {25} \
        CONFIG.PCW_I2C_RESET_ENABLE              {1} \
        CONFIG.PCW_IOPLL_CTRL_FBDIV              {42} \
        CONFIG.PCW_IO_IO_PLL_FREQMHZ             {1400.000} \
        CONFIG.PCW_MIO_0_DIRECTION  {out}   CONFIG.PCW_MIO_0_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_0_PULLUP  {disabled} CONFIG.PCW_MIO_0_SLEW  {slow} \
        CONFIG.PCW_MIO_1_DIRECTION  {inout} CONFIG.PCW_MIO_1_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_1_PULLUP  {enabled}  CONFIG.PCW_MIO_1_SLEW  {slow} \
        CONFIG.PCW_MIO_2_DIRECTION  {out}   CONFIG.PCW_MIO_2_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_2_PULLUP  {disabled} CONFIG.PCW_MIO_2_SLEW  {slow} \
        CONFIG.PCW_MIO_3_DIRECTION  {out}   CONFIG.PCW_MIO_3_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_3_PULLUP  {disabled} CONFIG.PCW_MIO_3_SLEW  {slow} \
        CONFIG.PCW_MIO_4_DIRECTION  {inout} CONFIG.PCW_MIO_4_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_4_PULLUP  {disabled} CONFIG.PCW_MIO_4_SLEW  {slow} \
        CONFIG.PCW_MIO_5_DIRECTION  {inout} CONFIG.PCW_MIO_5_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_5_PULLUP  {disabled} CONFIG.PCW_MIO_5_SLEW  {slow} \
        CONFIG.PCW_MIO_6_DIRECTION  {inout} CONFIG.PCW_MIO_6_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_6_PULLUP  {disabled} CONFIG.PCW_MIO_6_SLEW  {slow} \
        CONFIG.PCW_MIO_7_DIRECTION  {out}   CONFIG.PCW_MIO_7_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_7_PULLUP  {disabled} CONFIG.PCW_MIO_7_SLEW  {slow} \
        CONFIG.PCW_MIO_8_DIRECTION  {out}   CONFIG.PCW_MIO_8_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_8_PULLUP  {disabled} CONFIG.PCW_MIO_8_SLEW  {slow} \
        CONFIG.PCW_MIO_9_DIRECTION  {inout} CONFIG.PCW_MIO_9_IOTYPE  {LVCMOS 3.3V} CONFIG.PCW_MIO_9_PULLUP  {enabled}  CONFIG.PCW_MIO_9_SLEW  {slow} \
        CONFIG.PCW_MIO_10_DIRECTION {inout} CONFIG.PCW_MIO_10_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_10_PULLUP {enabled}  CONFIG.PCW_MIO_10_SLEW {slow} \
        CONFIG.PCW_MIO_11_DIRECTION {inout} CONFIG.PCW_MIO_11_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_11_PULLUP {enabled}  CONFIG.PCW_MIO_11_SLEW {slow} \
        CONFIG.PCW_MIO_12_DIRECTION {inout} CONFIG.PCW_MIO_12_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_12_PULLUP {enabled}  CONFIG.PCW_MIO_12_SLEW {slow} \
        CONFIG.PCW_MIO_13_DIRECTION {inout} CONFIG.PCW_MIO_13_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_13_PULLUP {enabled}  CONFIG.PCW_MIO_13_SLEW {slow} \
        CONFIG.PCW_MIO_14_DIRECTION {in}    CONFIG.PCW_MIO_14_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_14_PULLUP {disabled} CONFIG.PCW_MIO_14_SLEW {slow} \
        CONFIG.PCW_MIO_15_DIRECTION {inout} CONFIG.PCW_MIO_15_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_15_PULLUP {enabled}  CONFIG.PCW_MIO_15_SLEW {slow} \
        CONFIG.PCW_MIO_16_DIRECTION {inout} CONFIG.PCW_MIO_16_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_16_PULLUP {enabled}  CONFIG.PCW_MIO_16_SLEW {slow} \
        CONFIG.PCW_MIO_17_DIRECTION {inout} CONFIG.PCW_MIO_17_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_17_PULLUP {enabled}  CONFIG.PCW_MIO_17_SLEW {slow} \
        CONFIG.PCW_MIO_18_DIRECTION {inout} CONFIG.PCW_MIO_18_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_18_PULLUP {enabled}  CONFIG.PCW_MIO_18_SLEW {slow} \
        CONFIG.PCW_MIO_19_DIRECTION {inout} CONFIG.PCW_MIO_19_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_19_PULLUP {enabled}  CONFIG.PCW_MIO_19_SLEW {slow} \
        CONFIG.PCW_MIO_20_DIRECTION {inout} CONFIG.PCW_MIO_20_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_20_PULLUP {enabled}  CONFIG.PCW_MIO_20_SLEW {slow} \
        CONFIG.PCW_MIO_21_DIRECTION {inout} CONFIG.PCW_MIO_21_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_21_PULLUP {enabled}  CONFIG.PCW_MIO_21_SLEW {slow} \
        CONFIG.PCW_MIO_22_DIRECTION {inout} CONFIG.PCW_MIO_22_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_22_PULLUP {enabled}  CONFIG.PCW_MIO_22_SLEW {slow} \
        CONFIG.PCW_MIO_23_DIRECTION {inout} CONFIG.PCW_MIO_23_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_23_PULLUP {enabled}  CONFIG.PCW_MIO_23_SLEW {slow} \
        CONFIG.PCW_MIO_24_DIRECTION {out}   CONFIG.PCW_MIO_24_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_24_PULLUP {enabled}  CONFIG.PCW_MIO_24_SLEW {slow} \
        CONFIG.PCW_MIO_25_DIRECTION {in}    CONFIG.PCW_MIO_25_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_25_PULLUP {enabled}  CONFIG.PCW_MIO_25_SLEW {slow} \
        CONFIG.PCW_MIO_26_DIRECTION {inout} CONFIG.PCW_MIO_26_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_26_PULLUP {enabled}  CONFIG.PCW_MIO_26_SLEW {slow} \
        CONFIG.PCW_MIO_27_DIRECTION {inout} CONFIG.PCW_MIO_27_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_27_PULLUP {enabled}  CONFIG.PCW_MIO_27_SLEW {slow} \
        CONFIG.PCW_MIO_28_DIRECTION {inout} CONFIG.PCW_MIO_28_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_28_PULLUP {enabled}  CONFIG.PCW_MIO_28_SLEW {slow} \
        CONFIG.PCW_MIO_29_DIRECTION {inout} CONFIG.PCW_MIO_29_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_29_PULLUP {enabled}  CONFIG.PCW_MIO_29_SLEW {slow} \
        CONFIG.PCW_MIO_30_DIRECTION {inout} CONFIG.PCW_MIO_30_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_30_PULLUP {enabled}  CONFIG.PCW_MIO_30_SLEW {slow} \
        CONFIG.PCW_MIO_31_DIRECTION {inout} CONFIG.PCW_MIO_31_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_31_PULLUP {enabled}  CONFIG.PCW_MIO_31_SLEW {slow} \
        CONFIG.PCW_MIO_32_DIRECTION {inout} CONFIG.PCW_MIO_32_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_32_PULLUP {enabled}  CONFIG.PCW_MIO_32_SLEW {slow} \
        CONFIG.PCW_MIO_33_DIRECTION {inout} CONFIG.PCW_MIO_33_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_33_PULLUP {enabled}  CONFIG.PCW_MIO_33_SLEW {slow} \
        CONFIG.PCW_MIO_34_DIRECTION {in}    CONFIG.PCW_MIO_34_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_34_PULLUP {enabled}  CONFIG.PCW_MIO_34_SLEW {slow} \
        CONFIG.PCW_MIO_35_DIRECTION {inout} CONFIG.PCW_MIO_35_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_35_PULLUP {enabled}  CONFIG.PCW_MIO_35_SLEW {slow} \
        CONFIG.PCW_MIO_36_DIRECTION {inout} CONFIG.PCW_MIO_36_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_36_PULLUP {enabled}  CONFIG.PCW_MIO_36_SLEW {slow} \
        CONFIG.PCW_MIO_37_DIRECTION {inout} CONFIG.PCW_MIO_37_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_37_PULLUP {enabled}  CONFIG.PCW_MIO_37_SLEW {slow} \
        CONFIG.PCW_MIO_38_DIRECTION {inout} CONFIG.PCW_MIO_38_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_38_PULLUP {enabled}  CONFIG.PCW_MIO_38_SLEW {slow} \
        CONFIG.PCW_MIO_39_DIRECTION {inout} CONFIG.PCW_MIO_39_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_39_PULLUP {enabled}  CONFIG.PCW_MIO_39_SLEW {slow} \
        CONFIG.PCW_MIO_40_DIRECTION {inout} CONFIG.PCW_MIO_40_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_40_PULLUP {enabled}  CONFIG.PCW_MIO_40_SLEW {slow} \
        CONFIG.PCW_MIO_41_DIRECTION {inout} CONFIG.PCW_MIO_41_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_41_PULLUP {enabled}  CONFIG.PCW_MIO_41_SLEW {slow} \
        CONFIG.PCW_MIO_42_DIRECTION {inout} CONFIG.PCW_MIO_42_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_42_PULLUP {enabled}  CONFIG.PCW_MIO_42_SLEW {slow} \
        CONFIG.PCW_MIO_43_DIRECTION {inout} CONFIG.PCW_MIO_43_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_43_PULLUP {enabled}  CONFIG.PCW_MIO_43_SLEW {slow} \
        CONFIG.PCW_MIO_44_DIRECTION {inout} CONFIG.PCW_MIO_44_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_44_PULLUP {enabled}  CONFIG.PCW_MIO_44_SLEW {slow} \
        CONFIG.PCW_MIO_45_DIRECTION {inout} CONFIG.PCW_MIO_45_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_45_PULLUP {enabled}  CONFIG.PCW_MIO_45_SLEW {slow} \
        CONFIG.PCW_MIO_46_DIRECTION {inout} CONFIG.PCW_MIO_46_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_46_PULLUP {enabled}  CONFIG.PCW_MIO_46_SLEW {slow} \
        CONFIG.PCW_MIO_47_DIRECTION {inout} CONFIG.PCW_MIO_47_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_47_PULLUP {enabled}  CONFIG.PCW_MIO_47_SLEW {slow} \
        CONFIG.PCW_MIO_48_DIRECTION {inout} CONFIG.PCW_MIO_48_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_48_PULLUP {enabled}  CONFIG.PCW_MIO_48_SLEW {slow} \
        CONFIG.PCW_MIO_49_DIRECTION {inout} CONFIG.PCW_MIO_49_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_49_PULLUP {enabled}  CONFIG.PCW_MIO_49_SLEW {slow} \
        CONFIG.PCW_MIO_50_DIRECTION {inout} CONFIG.PCW_MIO_50_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_50_PULLUP {enabled}  CONFIG.PCW_MIO_50_SLEW {slow} \
        CONFIG.PCW_MIO_51_DIRECTION {inout} CONFIG.PCW_MIO_51_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_51_PULLUP {enabled}  CONFIG.PCW_MIO_51_SLEW {slow} \
        CONFIG.PCW_MIO_52_DIRECTION {inout} CONFIG.PCW_MIO_52_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_52_PULLUP {enabled}  CONFIG.PCW_MIO_52_SLEW {slow} \
        CONFIG.PCW_MIO_53_DIRECTION {inout} CONFIG.PCW_MIO_53_IOTYPE {LVCMOS 3.3V} CONFIG.PCW_MIO_53_PULLUP {enabled}  CONFIG.PCW_MIO_53_SLEW {slow} \
        CONFIG.PCW_MIO_TREE_PERIPHERALS \
{NAND Flash#GPIO#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#NAND Flash#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#UART 1#UART 1#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#SD 0#GPIO#GPIO#GPIO#GPIO#GPIO#SD 0#SD 0#SD 0#SD 0#SD 0#SD 0#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO#GPIO} \
        CONFIG.PCW_MIO_TREE_SIGNALS \
{cs#gpio[1]#ale#we_b#data[2]#data[0]#data[1]#cle#re_b#data[4]#data[5]#data[6]#data[7]#data[3]#busy#gpio[15]#gpio[16]#gpio[17]#gpio[18]#gpio[19]#gpio[20]#gpio[21]#gpio[22]#gpio[23]#tx#rx#gpio[26]#gpio[27]#gpio[28]#gpio[29]#gpio[30]#gpio[31]#gpio[32]#gpio[33]#cd#gpio[35]#gpio[36]#gpio[37]#gpio[38]#gpio[39]#clk#cmd#data[0]#data[1]#data[2]#data[3]#gpio[46]#gpio[47]#gpio[48]#gpio[49]#gpio[50]#gpio[51]#gpio[52]#gpio[53]} \
        CONFIG.PCW_NAND_CYCLES_T_AR  {10} \
        CONFIG.PCW_NAND_CYCLES_T_CLR {20} \
        CONFIG.PCW_NAND_CYCLES_T_RC  {50} \
        CONFIG.PCW_NAND_CYCLES_T_REA {20} \
        CONFIG.PCW_NAND_CYCLES_T_RR  {20} \
        CONFIG.PCW_NAND_CYCLES_T_WC  {50} \
        CONFIG.PCW_NAND_CYCLES_T_WP  {25} \
        CONFIG.PCW_NAND_GRP_D8_ENABLE     {0} \
        CONFIG.PCW_NAND_NAND_IO           {MIO 0 2.. 14} \
        CONFIG.PCW_NAND_PERIPHERAL_ENABLE {1} \
        CONFIG.PCW_NOR_GRP_A25_ENABLE     {0} \
        CONFIG.PCW_NOR_GRP_CS0_ENABLE     {0} \
        CONFIG.PCW_NOR_GRP_CS1_ENABLE     {0} \
        CONFIG.PCW_NOR_GRP_SRAM_CS0_ENABLE {0} \
        CONFIG.PCW_NOR_GRP_SRAM_CS1_ENABLE {0} \
        CONFIG.PCW_NOR_GRP_SRAM_INT_ENABLE {0} \
        CONFIG.PCW_NOR_PERIPHERAL_ENABLE  {0} \
        CONFIG.PCW_PCAP_PERIPHERAL_DIVISOR0 {7} \
        CONFIG.PCW_QSPI_GRP_FBCLK_ENABLE    {0} \
        CONFIG.PCW_QSPI_GRP_IO1_ENABLE      {0} \
        CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {0} \
        CONFIG.PCW_QSPI_GRP_SS1_ENABLE      {0} \
        CONFIG.PCW_QSPI_PERIPHERAL_DIVISOR0 {1} \
        CONFIG.PCW_QSPI_PERIPHERAL_ENABLE   {0} \
        CONFIG.PCW_QSPI_PERIPHERAL_FREQMHZ  {200} \
        CONFIG.PCW_SD0_GRP_CD_ENABLE        {1} \
        CONFIG.PCW_SD0_GRP_CD_IO            {MIO 34} \
        CONFIG.PCW_SD0_GRP_POW_ENABLE       {0} \
        CONFIG.PCW_SD0_GRP_WP_ENABLE        {0} \
        CONFIG.PCW_SD0_PERIPHERAL_ENABLE    {1} \
        CONFIG.PCW_SD0_SD0_IO               {MIO 40 .. 45} \
        CONFIG.PCW_SDIO_PERIPHERAL_DIVISOR0 {56} \
        CONFIG.PCW_SDIO_PERIPHERAL_FREQMHZ  {25} \
        CONFIG.PCW_SDIO_PERIPHERAL_VALID    {1} \
        CONFIG.PCW_SMC_PERIPHERAL_DIVISOR0  {14} \
        CONFIG.PCW_SMC_PERIPHERAL_FREQMHZ   {100} \
        CONFIG.PCW_SMC_PERIPHERAL_VALID     {1} \
        CONFIG.PCW_SPI_PERIPHERAL_DIVISOR0  {1} \
        CONFIG.PCW_TPIU_PERIPHERAL_DIVISOR0 {1} \
        CONFIG.PCW_UART1_GRP_FULL_ENABLE    {0} \
        CONFIG.PCW_UART1_PERIPHERAL_ENABLE  {1} \
        CONFIG.PCW_UART1_UART1_IO           {MIO 24 .. 25} \
        CONFIG.PCW_UART_PERIPHERAL_DIVISOR0 {14} \
        CONFIG.PCW_UART_PERIPHERAL_FREQMHZ  {100} \
        CONFIG.PCW_UART_PERIPHERAL_VALID    {1} \
        CONFIG.PCW_UIPARAM_ACT_DDR_FREQ_MHZ {533.333374} \
        CONFIG.PCW_UIPARAM_DDR_BANK_ADDR_COUNT {3} \
        CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH    {16 Bit} \
        CONFIG.PCW_UIPARAM_DDR_CL           {7} \
        CONFIG.PCW_UIPARAM_DDR_COL_ADDR_COUNT {10} \
        CONFIG.PCW_UIPARAM_DDR_CWL          {6} \
        CONFIG.PCW_UIPARAM_DDR_DEVICE_CAPACITY {2048 MBits} \
        CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH   {16 Bits} \
        CONFIG.PCW_UIPARAM_DDR_ECC          {Disabled} \
        CONFIG.PCW_UIPARAM_DDR_PARTNO       {MT41K128M16 JT-125} \
        CONFIG.PCW_UIPARAM_DDR_ROW_ADDR_COUNT {14} \
        CONFIG.PCW_UIPARAM_DDR_SPEED_BIN    {DDR3_1066F} \
        CONFIG.PCW_UIPARAM_DDR_T_FAW        {40.0} \
        CONFIG.PCW_UIPARAM_DDR_T_RAS_MIN    {35.0} \
        CONFIG.PCW_UIPARAM_DDR_T_RC         {48.75} \
        CONFIG.PCW_UIPARAM_DDR_T_RCD        {7} \
        CONFIG.PCW_UIPARAM_DDR_T_RP         {7} \
        CONFIG.PCW_USB0_RESET_ENABLE        {0} \
        CONFIG.PCW_USB1_RESET_ENABLE        {0} \
        CONFIG.PCW_USB_RESET_ENABLE         {1} \
        CONFIG.PCW_USE_M_AXI_GP0            {0} \
    ] $ps7

    # ── xlconcat_0 : agrega RXD nibble baixo + nibble alto → 8 bits ───────────
    set xlconcat_0 [create_bd_cell -type ip \
                        -vlnv xilinx.com:ip:xlconcat:2.1 xlconcat_0]
    set_property -dict [list \
        CONFIG.NUM_PORTS {2} \
        CONFIG.IN0_WIDTH {4} \
        CONFIG.IN1_WIDTH {4} \
    ] $xlconcat_0

    # ── xlslice_0 : TXD[7:0] → 4 bits para o PHY ──────────────────────────────
    set xlslice_0 [create_bd_cell -type ip \
                       -vlnv xilinx.com:ip:xlslice:1.0 xlslice_0]
    set_property -dict [list \
        CONFIG.DIN_WIDTH {8} \
        CONFIG.DIN_FROM  {3} \
        CONFIG.DIN_TO    {0} \
        CONFIG.DOUT_WIDTH {4} \
    ] $xlslice_0

    # ── xlslice_1 : GPIO_O[63:0] bits[1:0] → LED[1:0] ─────────────────────────
    set xlslice_1 [create_bd_cell -type ip \
                       -vlnv xilinx.com:ip:xlslice:1.0 xlslice_1]
    set_property -dict [list \
        CONFIG.DIN_FROM  {1} \
        CONFIG.DIN_WIDTH {64} \
        CONFIG.DOUT_WIDTH {2} \
    ] $xlslice_1

    # ── Conexões de interface ──────────────────────────────────────────────────
    connect_bd_intf_net [get_bd_intf_ports DDR]               [get_bd_intf_pins processing_system7_0/DDR]
    connect_bd_intf_net [get_bd_intf_ports FIXED_IO]          [get_bd_intf_pins processing_system7_0/FIXED_IO]
    connect_bd_intf_net [get_bd_intf_ports MDIO_ETHERNET_0_0] [get_bd_intf_pins processing_system7_0/MDIO_ETHERNET_0]

    # ── Conexões de sinal ──────────────────────────────────────────────────────
    connect_bd_net [get_bd_ports ENET0_GMII_RX_CLK_0] [get_bd_pins processing_system7_0/ENET0_GMII_RX_CLK]
    connect_bd_net [get_bd_ports ENET0_GMII_RX_DV_0]  [get_bd_pins processing_system7_0/ENET0_GMII_RX_DV]
    connect_bd_net [get_bd_ports ENET0_GMII_TX_CLK_0] [get_bd_pins processing_system7_0/ENET0_GMII_TX_CLK]
    connect_bd_net [get_bd_pins processing_system7_0/ENET0_GMII_TX_EN] [get_bd_ports ENET0_GMII_TX_EN_0]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK3]        [get_bd_ports FCLK_CLK3_0]

    connect_bd_net [get_bd_ports enet0_gmii_rxd]      [get_bd_pins xlconcat_0/In0]
    connect_bd_net [get_bd_pins xlconcat_0/dout]       [get_bd_pins processing_system7_0/ENET0_GMII_RXD]

    connect_bd_net [get_bd_pins processing_system7_0/ENET0_GMII_TXD] [get_bd_pins xlslice_0/Din]
    connect_bd_net [get_bd_pins xlslice_0/Dout]        [get_bd_ports enet0_gmii_txd]

    connect_bd_net [get_bd_pins processing_system7_0/GPIO_O] [get_bd_pins xlslice_1/Din]
    connect_bd_net [get_bd_pins xlslice_1/Dout]              [get_bd_ports LED]

    # ── Validar e salvar ───────────────────────────────────────────────────────
    validate_bd_design
    save_bd_design
    close_bd_design "ebaz4205"
}

cr_bd_ebaz4205

# =============================================================================
# 3. Gerar wrapper e definir como top
# =============================================================================
set bd_file [get_files -norecurse ebaz4205.bd]
set_property REGISTERED_WITH_MANAGER 1          $bd_file
set_property SYNTH_CHECKPOINT_MODE  Hierarchical $bd_file

set wrapper_path [make_wrapper -fileset sources_1 -files $bd_file -top]
add_files -norecurse -fileset sources_1 $wrapper_path

set_property top          ebaz4205_wrapper [get_filesets sources_1]
set_property top_auto_set 0                [get_filesets sources_1]

# =============================================================================
# 4. Adicionar constraints
# =============================================================================
if {[file exists $xdc_file]} {
    add_files -fileset constrs_1 -norecurse $xdc_file
    set_property target_constrs_file $xdc_file [get_filesets constrs_1]
    puts "XDC adicionado: $xdc_file"
} else {
    puts "AVISO: XDC não encontrado em $xdc_file — adicione manualmente."
}

puts ""
puts "============================================================"
puts " Projeto criado: $proj_dir"
puts " BD: ebaz4205  |  Top: ebaz4205_wrapper"
puts " FCLK0=50MHz, FCLK3=25MHz, ENET0 EMIO, LED via GPIO_O[1:0]"
puts "============================================================"

# =============================================================================
# 5. mult_gen IP (BilienarSolverUnit_DSP) + filesets de simulação
# =============================================================================
set root_dir [file normalize "$script_dir/../.."]

# ── 5a. Criar IP mult_gen 42×42 signed ───────────────────────────────────────
puts ""
puts "=== \[5/5\] Criando IP BilienarSolverUnit_DSP (mult_gen 42x42) ==="

create_ip -name mult_gen -vendor xilinx.com -library ip -version 12.0 \
    -module_name BilienarSolverUnit_DSP

set_property -dict [list \
    CONFIG.PortAWidth       {42}                  \
    CONFIG.PortBWidth       {42}                  \
    CONFIG.MultType         {Parallel_Multiplier}  \
    CONFIG.PortAType        {Signed}              \
    CONFIG.PortBType        {Signed}              \
    CONFIG.OptGoal          {Speed}               \
    CONFIG.PipeStages       {7}                   \
    CONFIG.OutputWidthHigh  {83}                  \
    CONFIG.OutputWidthLow   {0}                   \
] [get_ips BilienarSolverUnit_DSP]

generate_target {simulation instantiation_template} \
    [get_files BilienarSolverUnit_DSP.xci]

puts "  IP BilienarSolverUnit_DSP criado e targets de simulação gerados."

# ── 5b. Fileset sim_compare (tb_DSP_StubVsIP) ────────────────────────────────
puts ""
puts "=== Criando fileset sim_compare ==="

if {[get_filesets -quiet sim_compare] eq ""} {
    create_fileset -simset sim_compare
}

# BilinearSolverPkg needed by testbench (FP_TOTAL_BITS, to_fp)
add_files -fileset sim_compare -norecurse \
    $root_dir/common/modules/bilinear_solver/src/BilinearSolverPkg.vhd

# NOTE: BilienarSolverUnit_DSP.vhd (common/modules) NOT added.
# The IP sim file already provides the entity; the source would overwrite it
# adding a LATENCY generic, causing a redeclaration error.

# Self-contained stub entity (BilienarSolverUnit_DSP_Sim) — always included by compile order
add_files -fileset sim_compare -norecurse \
    $root_dir/src/tb/BilienarSolverUnit_DSP_Sim.vhd

# Testbench
add_files -fileset sim_compare -norecurse \
    $root_dir/src/tb/tb_DSP_StubVsIP.vhd

set_property top     tb_DSP_StubVsIP [get_filesets sim_compare]
set_property top_lib xil_defaultlib  [get_filesets sim_compare]
update_compile_order -fileset sim_compare
puts "  sim_compare criado."

# ── 5c. Fileset sim_bsu_compare (tb_BSU_StubVsIP) ────────────────────────────
puts ""
puts "=== Criando fileset sim_bsu_compare ==="

if {[get_filesets -quiet sim_bsu_compare] eq ""} {
    create_fileset -simset sim_bsu_compare
}

# RTL sources
# NOTE: BilienarSolverUnit_DSP.vhd (common/modules) NOT added — same reason as sim_compare.
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/common/modules/bilinear_solver/src/BilinearSolverPkg.vhd
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/common/modules/bilinear_solver/src/BilinearSolverUnit.vhd

# Self-contained stub entity (BilienarSolverUnit_DSP_Sim) — always included by compile order
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/BilienarSolverUnit_DSP_Sim.vhd

# Test architecture wrapper + testbench
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/BilinearSolverUnit_TestArch.vhd
add_files -fileset sim_bsu_compare -norecurse \
    $root_dir/src/tb/tb_BSU_StubVsIP.vhd

set_property top     tb_BSU_StubVsIP [get_filesets sim_bsu_compare]
set_property top_lib xil_defaultlib  [get_filesets sim_bsu_compare]
update_compile_order -fileset sim_bsu_compare
puts "  sim_bsu_compare criado."

puts ""
puts "============================================================"
puts " IPs e filesets de simulação prontos:"
puts "   IP:            BilienarSolverUnit_DSP (mult_gen 42x42)"
puts "   sim_compare:   tb_DSP_StubVsIP"
puts "   sim_bsu_compare: tb_BSU_StubVsIP"
puts " Próximos passos:"
puts "   make sim-dsp-compare"
puts "   make sim-bsu-compare"
puts "============================================================"
