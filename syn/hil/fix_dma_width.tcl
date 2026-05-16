# =============================================================================
# fix_dma_width.tcl
#
# Patches the existing block design to fix the DMAIntErr issue on the
# 256-bit DMA → 64-bit HP0 path.
#
# Root cause:
#   axi_dma_0 was at 256-bit on both M_AXI_S2MM (memory) and S_AXIS_S2MM
#   (stream). The smartconnect between DMA and HP0 was supposed to handle
#   256→64 conversion + AXI4→AXI3 + burst splitting, but in practice this
#   produces DMAIntErr on Zynq-7 (HP0 is fixed 64-bit AXI3, max 16 beats).
#
# Fix:
#   1. Reconfigure axi_dma_0 with both stream and memory sides at 64 bits
#      → matches HP0 natively. Smartconnect now only does AXI4→AXI3 protocol
#      conversion (no width conversion, no burst splitting).
#   2. Add axis_dwidth_converter:1.1 between hil_axi_top_0/m_axis (256b) and
#      axi_dma_0/S_AXIS_S2MM (64b).
#   3. Route carrier_tick_o and s2mm_introut through xlconcat to IRQ_F2P.
#
# After running this, run 'make synth' to rebuild the bitstream.
#
# Usage:
#   /opt/Xilinx/2025.1/Vivado/bin/vivado -mode batch -source fix_dma_width.tcl
# =============================================================================

set proj_file "[file normalize [file join [file dirname [info script]] ebaz4205/ebaz4205.xpr]]"
set_param general.maxThreads 4

open_project $proj_file

set bd_files [get_files -filter {FILE_TYPE == "Block Designs"}]
if {[llength $bd_files] == 0} { error "No block design found" }
set bd [lindex $bd_files 0]
puts "Opening block design: $bd"
open_bd_design $bd

# ── 1. Reconfigure axi_dma_0 to 64-bit on both stream and memory ─────────
set cur_mwidth [get_property CONFIG.c_m_axi_s2mm_data_width [get_bd_cells axi_dma_0]]
set cur_swidth [get_property CONFIG.c_s_axis_s2mm_tdata_width [get_bd_cells axi_dma_0]]
puts "axi_dma_0 before: m=$cur_mwidth s=$cur_swidth"

if {$cur_mwidth != 64 || $cur_swidth != 64} {
    set_property -dict [list \
        CONFIG.c_s_axis_s2mm_tdata_width {64} \
        CONFIG.c_m_axi_s2mm_data_width   {64} \
    ] [get_bd_cells axi_dma_0]
    puts "axi_dma_0 reconfigured to 64-bit on stream and memory."
}

# ── 2. Insert axis_dwidth_converter (256 → 64) if not present ────────────
set dwc [get_bd_cells -quiet axis_dwidth_converter_0]
if {[llength $dwc] == 0} {
    puts "Creating axis_dwidth_converter_0 (256b → 64b)..."
    set dwc [create_bd_cell -type ip \
                 -vlnv xilinx.com:ip:axis_dwidth_converter:1.1 \
                 axis_dwidth_converter_0]
    set_property -dict [list \
        CONFIG.S_TDATA_NUM_BYTES {32} \
        CONFIG.M_TDATA_NUM_BYTES {8}  \
        CONFIG.HAS_TLAST         {1}  \
        CONFIG.HAS_TKEEP         {1}  \
    ] $dwc
} else {
    puts "axis_dwidth_converter_0 already present, ensuring config..."
    set_property -dict [list \
        CONFIG.S_TDATA_NUM_BYTES {32} \
        CONFIG.M_TDATA_NUM_BYTES {8}  \
        CONFIG.HAS_TLAST         {1}  \
        CONFIG.HAS_TKEEP         {1}  \
    ] $dwc
}

# ── 3. Disconnect direct FPGA→DMA, connect through the dwidth converter ──
# Remove old direct link if present
set old_net [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins hil_axi_top_0/m_axis]]
if {[llength $old_net] > 0} {
    set conn_pins [get_bd_intf_pins -of_objects $old_net]
    set tgt_pin [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
    if {[lsearch -exact $conn_pins $tgt_pin] != -1} {
        puts "Disconnecting old direct stream link..."
        delete_bd_objs $old_net
    }
}

# Connect FPGA m_axis → dwc S_AXIS (if not already)
if {[llength [get_bd_intf_nets -quiet -of_objects \
        [get_bd_intf_pins axis_dwidth_converter_0/S_AXIS]]] == 0} {
    connect_bd_intf_net \
        [get_bd_intf_pins hil_axi_top_0/m_axis] \
        [get_bd_intf_pins axis_dwidth_converter_0/S_AXIS]
}

# Connect dwc M_AXIS → DMA S_AXIS_S2MM (if not already)
if {[llength [get_bd_intf_nets -quiet -of_objects \
        [get_bd_intf_pins axis_dwidth_converter_0/M_AXIS]]] == 0} {
    connect_bd_intf_net \
        [get_bd_intf_pins axis_dwidth_converter_0/M_AXIS] \
        [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
}

# Clock and reset for the dwidth converter (FCLK0 + proc_sys_reset_0)
if {[llength [get_bd_nets -quiet -of_objects \
        [get_bd_pins axis_dwidth_converter_0/aclk]]] == 0} {
    connect_bd_net \
        [get_bd_pins processing_system7_0/FCLK_CLK0] \
        [get_bd_pins axis_dwidth_converter_0/aclk]
}
if {[llength [get_bd_nets -quiet -of_objects \
        [get_bd_pins axis_dwidth_converter_0/aresetn]]] == 0} {
    connect_bd_net \
        [get_bd_pins proc_sys_reset_0/peripheral_aresetn] \
        [get_bd_pins axis_dwidth_converter_0/aresetn]
}

# ── 4. Route DMA interrupt to PS IRQ_F2P[1] while keeping carrier on [0] ───
set irq_concat [get_bd_cells -quiet irq_concat_0]
if {[llength $irq_concat] == 0} {
    puts "Creating irq_concat_0 for carrier_tick_o + DMA S2MM IRQ..."
    set irq_concat [create_bd_cell -type ip \
        -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat_0]
}
set_property -dict [list \
    CONFIG.NUM_PORTS {2} \
    CONFIG.IN0_WIDTH {1} \
    CONFIG.IN1_WIDTH {1} \
] $irq_concat

set irq_pin [get_bd_pins processing_system7_0/IRQ_F2P]
set irq_net [get_bd_nets -quiet -of_objects $irq_pin]
if {[llength $irq_net] > 0} {
    set irq_pins [get_bd_pins -of_objects $irq_net]
    if {[lsearch -exact $irq_pins [get_bd_pins irq_concat_0/dout]] == -1} {
        puts "Disconnecting old direct IRQ_F2P net..."
        delete_bd_objs $irq_net
    }
}

if {[llength [get_bd_nets -quiet -of_objects \
        [get_bd_pins irq_concat_0/In0]]] == 0} {
    connect_bd_net \
        [get_bd_pins hil_axi_top_0/carrier_tick_o] \
        [get_bd_pins irq_concat_0/In0]
}
if {[llength [get_bd_nets -quiet -of_objects \
        [get_bd_pins irq_concat_0/In1]]] == 0} {
    connect_bd_net \
        [get_bd_pins axi_dma_0/s2mm_introut] \
        [get_bd_pins irq_concat_0/In1]
}
if {[llength [get_bd_nets -quiet -of_objects $irq_pin]] == 0} {
    connect_bd_net \
        [get_bd_pins irq_concat_0/dout] \
        $irq_pin
}

# ── 5. Validate, save, regenerate ────────────────────────────────────────
puts "Validating BD..."
validate_bd_design
save_bd_design
puts "Block design saved."

close_bd_design [get_bd_designs ebaz4205]

puts "Regenerating output products..."
generate_target all $bd_files
export_ip_user_files -of_objects $bd_files -no_script -sync -force -quiet

# Reset runs so they re-synthesize against the new BD
set ooc_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}]
foreach r $ooc_runs { reset_run $r }
reset_run synth_1
reset_run impl_1

close_project
puts ""
puts "============================================================"
puts " BD patched: dwc 256→64 inserted, DMA at 64b/64b"
puts " Next: run 'make synth' to rebuild bitstream"
puts "============================================================"
