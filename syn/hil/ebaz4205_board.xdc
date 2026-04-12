# =============================================================================
# ebaz4205_board.xdc
# Constraints para EBAZ4205 (Zynq-7010, xc7z010clg400-1)
# Top-level: ebaz4205_wrapper (BD ebaz4205)
# =============================================================================

# -----------------------------------------------------------------------------
# LEDs — GPIO_O[1:0] via xlslice_1 → LED[1:0]
#   LED[0] = verde (W13)
#   LED[1] = vermelho (W14)
# -----------------------------------------------------------------------------
set_property PACKAGE_PIN W13 [get_ports {LED[0]}]
set_property PACKAGE_PIN W14 [get_ports {LED[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {LED[*]}]

# -----------------------------------------------------------------------------
# Ethernet PHY (IP101GA) via EMIO
# -----------------------------------------------------------------------------
set_property PACKAGE_PIN U14 [get_ports ENET0_GMII_RX_CLK_0]
set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_RX_CLK_0]

set_property PACKAGE_PIN U15 [get_ports ENET0_GMII_TX_CLK_0]
set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_TX_CLK_0]

set_property PACKAGE_PIN W16 [get_ports ENET0_GMII_RX_DV_0]
set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_RX_DV_0]

set_property PACKAGE_PIN W19 [get_ports ENET0_GMII_TX_EN_0]
set_property IOSTANDARD LVCMOS33 [get_ports ENET0_GMII_TX_EN_0]

set_property PACKAGE_PIN U18 [get_ports FCLK_CLK3_0]
set_property IOSTANDARD LVCMOS33 [get_ports FCLK_CLK3_0]

set_property PACKAGE_PIN Y16 [get_ports {enet0_gmii_rxd[0]}]
set_property PACKAGE_PIN V16 [get_ports {enet0_gmii_rxd[1]}]
set_property PACKAGE_PIN V17 [get_ports {enet0_gmii_rxd[2]}]
set_property PACKAGE_PIN Y17 [get_ports {enet0_gmii_rxd[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {enet0_gmii_rxd[*]}]

set_property PACKAGE_PIN W18 [get_ports {enet0_gmii_txd[0]}]
set_property PACKAGE_PIN Y18 [get_ports {enet0_gmii_txd[1]}]
set_property PACKAGE_PIN V18 [get_ports {enet0_gmii_txd[2]}]
set_property PACKAGE_PIN Y19 [get_ports {enet0_gmii_txd[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {enet0_gmii_txd[*]}]

set_property PACKAGE_PIN W15 [get_ports MDIO_ETHERNET_0_0_mdc]
set_property IOSTANDARD LVCMOS33 [get_ports MDIO_ETHERNET_0_0_mdc]

set_property PACKAGE_PIN Y14 [get_ports MDIO_ETHERNET_0_0_mdio_io]
set_property IOSTANDARD LVCMOS33 [get_ports MDIO_ETHERNET_0_0_mdio_io]

# -----------------------------------------------------------------------------
# Timing — false paths em I/O assíncronos
# -----------------------------------------------------------------------------
set_false_path -to   [get_ports {LED[*]}]
set_false_path -to   [get_ports {enet0_gmii_txd[*] ENET0_GMII_TX_EN_0 FCLK_CLK3_0 MDIO_ETHERNET_0_0_mdc}]
set_false_path -from [get_ports {enet0_gmii_rxd[*] ENET0_GMII_RX_DV_0 ENET0_GMII_RX_CLK_0 ENET0_GMII_TX_CLK_0 MDIO_ETHERNET_0_0_mdio_io}]
