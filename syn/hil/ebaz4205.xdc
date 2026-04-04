# =============================================================================
# ebaz4205.xdc
# Constraints for EBAZ4205 (Zynq-7010, xc7z010clg400-1)
# PL I/O Banks 34/35: VCCO = 3.3V
#
# PS-side pins (DDR, FIXED_IO) are NOT constrained here — handled by PS7
# =============================================================================

# -----------------------------------------------------------------------------
# LEDs (status indicators)
# -----------------------------------------------------------------------------
set_property PACKAGE_PIN W13 [get_ports led_green_o]
set_property IOSTANDARD  LVCMOS33 [get_ports led_green_o]

set_property PACKAGE_PIN W14 [get_ports led_red_o]
set_property IOSTANDARD  LVCMOS33 [get_ports led_red_o]

# -----------------------------------------------------------------------------
# UART (J7 header — requires soldering on EBAZ4205)
# F19 = RX (data in from PC/App)
# F20 = TX (data out to PC/App)
# -----------------------------------------------------------------------------
set_property PACKAGE_PIN F19 [get_ports uart_rx_i]
set_property IOSTANDARD  LVCMOS33 [get_ports uart_rx_i]

set_property PACKAGE_PIN F20 [get_ports uart_tx_o]
set_property IOSTANDARD  LVCMOS33 [get_ports uart_tx_o]

# -----------------------------------------------------------------------------
# Gate Outputs — DATA1 connector (2mm pitch, 20-pin)
# 12 signals: 3 phases × 4 switches (S1/S2/S3/S4) per phase
#
# Pin layout (DATA1):
#  1-2  = Vcc   3-4  = GND   10 = NC   12 = GND
#  5=A20  6=H16  7=B19  8=B20
#  9=C20  11=H17  13=D20  14=D18
#  15=H18  16=D19  17=F20* 18=E19  19=F19*  20=K17
#  (* F19/F20 shared with UART header — use DATA2/DATA3 if conflict)
# -----------------------------------------------------------------------------

# Phase A: S1 S2 S3 S4
set_property PACKAGE_PIN A20 [get_ports {pwm_a_o[0]}]
set_property PACKAGE_PIN H16 [get_ports {pwm_a_o[1]}]
set_property PACKAGE_PIN B19 [get_ports {pwm_a_o[2]}]
set_property PACKAGE_PIN B20 [get_ports {pwm_a_o[3]}]

# Phase B: S1 S2 S3 S4
set_property PACKAGE_PIN C20 [get_ports {pwm_b_o[0]}]
set_property PACKAGE_PIN H17 [get_ports {pwm_b_o[1]}]
set_property PACKAGE_PIN D20 [get_ports {pwm_b_o[2]}]
set_property PACKAGE_PIN D18 [get_ports {pwm_b_o[3]}]

# Phase C: S1 S2 S3 S4  (using DATA1 remaining pins)
set_property PACKAGE_PIN H18 [get_ports {pwm_c_o[0]}]
set_property PACKAGE_PIN D19 [get_ports {pwm_c_o[1]}]
set_property PACKAGE_PIN E19 [get_ports {pwm_c_o[2]}]
set_property PACKAGE_PIN K17 [get_ports {pwm_c_o[3]}]

set_property IOSTANDARD LVCMOS33 [get_ports {pwm_a_o[*]}]
set_property IOSTANDARD LVCMOS33 [get_ports {pwm_b_o[*]}]
set_property IOSTANDARD LVCMOS33 [get_ports {pwm_c_o[*]}]

# -----------------------------------------------------------------------------
# Timing
# FCLK_CLK0 is auto-constrained by PS7 primitive (100 MHz)
# Gate outputs and LEDs are asynchronous outputs — false path
# -----------------------------------------------------------------------------
set_false_path -to [get_ports {pwm_a_o[*] pwm_b_o[*] pwm_c_o[*]}]
set_false_path -to [get_ports {led_green_o led_red_o}]
set_false_path -to [get_ports uart_tx_o]
set_false_path -from [get_ports uart_rx_i]

