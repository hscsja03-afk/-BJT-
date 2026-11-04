# Vivado 2026.1, rebuilt from source. Does not connect to hardware.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set profile [expr {[llength $argv] ? [lindex $argv 0] : "baseline50"}]
if {$profile ni {baseline50 pynq_custom50 pynq_adc50_dac125 target125_250}} {error "Unknown profile $profile"}
if {![string match 2026.1* [version -short]]} {error "This migration must be checked with Vivado 2026.1"}
set out $root/build/work/$profile
if {[llength $argv] > 2} {
    set candidate [file normalize [lindex $argv 2]]
    if {![string match "$root/build/work/*" $candidate]} {error "Build directory must be inside build/work"}
    set out $candidate
}
file mkdir $out
set f [open $out/build_status.txt w];puts $f "BUILD_IN_PROGRESS";close $f
create_project bjt $out/vivado -part xc7z020clg400-2 -force
set_property target_language Verilog [current_project]
set divider [expr {$profile eq "target125_250" ? 4 : ($profile eq "pynq_adc50_dac125" ? 8 : 20)}]
set phase [expr {$profile eq "target125_250" ? 202.5 : ($profile eq "pynq_adc50_dac125" ? 146.25 : 0.0)}]
set adc_divider [expr {$profile eq "target125_250" ? 8 : 20}]
if {[llength $argv]>3} {set adc_divider [lindex $argv 3]}
if {$adc_divider ni {8 10 12 16 20}} {error "Unsupported ADC divider"}
set defines [list ADDA_TX1 ADDA_GPIO ADDA_DAC_GUI ADDA_DAC_DIVIDER=$divider ADDA_DAC_PHASE=$phase ADDA_ADC_DIVIDER=$adc_divider]
set lcd_ddr [expr {[llength $argv]>4 && [lindex $argv 4] eq "lcd_ddr"}]
if {$lcd_ddr} {lappend defines ADDA_LCD_DDR}
set_property verilog_define $defines [current_fileset]
# Module-reference port discovery requires the feature macros in the file itself.
set f [open $root/src/rtl/adda_core.v]; set core [read $f]; close $f
set f [open $out/adda_core.v w]
if {$lcd_ddr} {puts $f "`define ADDA_LCD_DDR"}
puts $f "`define ADDA_TX1\n`define ADDA_GPIO\n`define ADDA_DAC_GUI\n`define ADDA_ADC_DIVIDER $adc_divider\n$core"; close $f
foreach f [concat [glob $root/src/rtl/*.v] [glob $root/src/rtl/*.sv] [glob $root/src/rtl/touch/*v]] {
    if {[file tail $f] ne "adda_core.v"} {add_files $f}
}
add_files $out/adda_core.v
add_files [concat [glob $root/src/assets/*.mem] [glob $root/src/rtl/*.mem]]
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
# Overlay-only default preserves the legacy electrical/MIO map. A bootable
# Linux overlay must supply the matching board-specific PS preset below.
set_property -dict [list CONFIG.PCW_UIPARAM_DDR_ENABLE {0} CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} \
    CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} CONFIG.PCW_UART0_UART0_IO {MIO 14 .. 15} \
    CONFIG.PCW_UART0_BAUD_RATE {115200} CONFIG.PCW_GPIO_MIO_GPIO_ENABLE {1} \
    CONFIG.PCW_GPIO_MIO_GPIO_IO {MIO} CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} CONFIG.PCW_ENET0_PERIPHERAL_FREQMHZ {1000 Mbps}] $ps
set ps_preset_supplied 0
if {[llength $argv] > 1} {
    # Preset script receives $ps. Use a source-reviewed, board-specific preset.
    source [file normalize [lindex $argv 1]]
    if {![get_property CONFIG.PCW_UIPARAM_DDR_ENABLE $ps]} {error "Linux preset must enable actual DDR"}
    set ps_preset_supplied 1
}
set external_ps_ports {FIXED_IO}
if {$ps_preset_supplied} {set external_ps_ports {FIXED_IO DDR}}
set ps_automation_config [format {make_external "%s" apply_board_preset "0" Master "Disable" Slave "Disable"} [join $external_ps_ports {, }]]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config $ps_automation_config $ps
# DDR is PS-only; this top is for overlay use, not for generating BOOT.BIN.
set core [create_bd_cell -type module -reference adda_core adda_core_0]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins adda_core_0/bus_clk]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7/M_AXI_GP0" Clk_master "/ps7/FCLK_CLK0 (50 MHz)" Clk_slave "/ps7/FCLK_CLK0 (50 MHz)" Clk_xbar "/ps7/FCLK_CLK0 (50 MHz)" intc_ip "New AXI Interconnect" master_apm "0"} [get_bd_intf_pins adda_core_0/S_AXI]
foreach name {adc_dco_a adc_dco_b dac_dco adc_a adc_b adc_or_a adc_or_b dac_a dac_b clkgen_reset_n clkgen_sync_n clkgen_ld clkgen_status clkgen_refmon tx1_scl tx1_sda} {
    make_bd_pins_external [get_bd_pins adda_core_0/$name]
    set_property name $name [get_bd_ports ${name}_0]
}
foreach {name dir width} {gpio_cmd_valid O 1 gpio_cmd_mask O 7 gpio_cmd_value O 7 gpio_state I 7 gpio_sense I 7 gpio_sequence I 32 ui_event I 32 ui_ack O 1 ui_page O 2 ui_write O 1 ui_word O 32} {
    if {$width==1} {create_bd_port -dir $dir $name} else {create_bd_port -dir $dir -from [expr {$width-1}] -to 0 $name}
    connect_bd_net [get_bd_pins adda_core_0/$name] [get_bd_ports $name]
}
create_bd_port -dir O -type clk lcd_bus_clk
set_property CONFIG.FREQ_HZ 50000000 [get_bd_ports lcd_bus_clk]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_ports lcd_bus_clk]
create_bd_port -dir O -type rst lcd_bus_reset_n
connect_bd_net [get_bd_pins adda_core_0/reset_n] [get_bd_ports lcd_bus_reset_n]
if {$lcd_ddr} {
    if {!$ps_preset_supplied} {error "LCD DDR requires reviewed Linux DDR preset"}
    set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {64}] $ps
    set reader [create_bd_cell -type module -reference lcd_ddr_reader lcd_ddr_0]
    connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins lcd_ddr_0/clk] [get_bd_pins ps7/S_AXI_HP0_ACLK]
    connect_bd_net [get_bd_pins adda_core_0/reset_n] [get_bd_pins lcd_ddr_0/reset_n]
    foreach signal {ui_write ui_word} {
        connect_bd_net [get_bd_pins adda_core_0/$signal] [get_bd_pins lcd_ddr_0/$signal]
    }
    connect_bd_net [get_bd_pins lcd_ddr_0/status] [get_bd_pins adda_core_0/lcd_status]
    connect_bd_net [get_bd_pins lcd_ddr_0/faults] [get_bd_pins adda_core_0/lcd_faults]
    foreach {port pin dir width} {ddr_enabled enabled O 1 ddr_rgb rgb O 24 ddr_h_count h_count I 11 ddr_v_count v_count I 10 ddr_scan_x scan_x I 11 ddr_scan_y scan_y I 10 ddr_active scan_active I 1 ddr_frame_start frame_start I 1} {
        if {$width==1} {create_bd_port -dir $dir $port} else {create_bd_port -dir $dir -from [expr {$width-1}] -to 0 $port}
        connect_bd_net [get_bd_pins lcd_ddr_0/$pin] [get_bd_ports $port]
    }
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/lcd_ddr_0/M_AXI" Slave "/ps7/S_AXI_HP0" Clk_master "/ps7/FCLK_CLK0 (50 MHz)" Clk_slave "/ps7/FCLK_CLK0 (50 MHz)" intc_ip "New AXI Interconnect" master_apm "0"} [get_bd_intf_pins ps7/S_AXI_HP0]
    assign_bd_address
}
assign_bd_address -offset 0x43C00000 -range 64K -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs adda_core_0/S_AXI/reg0] -force
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
set_property top adda_dac_gui_top [current_fileset]
set f [open $root/src/constraints/timing.xdc];set timing [read $f];close $f
if {$profile eq "pynq_adc50_dac125"} {
    # Keep ADC at 50 MSPS and preserve all PCB/translator delay envelopes.
    # This candidate is exported only when both setup and hold pass.
    set timing [string map [list \
        {create_clock -name dac_clk -period 20.000 [get_ports dac_dco]} {create_clock -name dac_clk -period 8.000 [get_ports dac_dco]
create_clock -name dac_capture -period 8.000 -waveform {5.600 9.600}} \
        {set_output_delay -clock dac_clk -max 4.500} {set_output_delay -clock dac_capture -max 2.100} \
        {set_output_delay -clock dac_clk -min 0.800} {set_output_delay -clock dac_capture -min -1.600} \
        {{adc_clk_a adc_clk_b dac_clk}} {{adc_clk_a adc_clk_b dac_clk dac_capture}} \
        {[get_clocks -include_generated_clocks dac_clk]} {[get_clocks -include_generated_clocks {dac_clk dac_capture}]} \
        {set_bus_skew 20.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cd/gray_reg*}]} \
        {set_bus_skew 8.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cd/gray_reg*}]}] $timing]
}
if {$profile eq "target125_250"} {
    # Retain the external input and output delay envelopes.
    set timing [string map [list \
        {create_clock -name adc_clk_a -period 20.000} {create_clock -name adc_clk_a -period 8.000} \
        {create_clock -name adc_clk_b -period 20.000} {create_clock -name adc_clk_b -period 8.000} \
        {create_clock -name dac_clk -period 20.000 [get_ports dac_dco]} {create_clock -name dac_clk -period 4.000 [get_ports dac_dco]
create_clock -name dac_capture -period 4.000 -waveform {1.600 3.600}} \
        {set_output_delay -clock dac_clk -max 4.500} {set_output_delay -clock dac_capture -max 2.100} \
        {set_output_delay -clock dac_clk -min 0.800} {set_output_delay -clock dac_capture -min -1.600} \
        {{adc_clk_a adc_clk_b dac_clk}} {{adc_clk_a adc_clk_b dac_clk dac_capture}} \
        {[get_clocks -include_generated_clocks dac_clk]} {[get_clocks -include_generated_clocks {dac_clk dac_capture}]} \
        {set_bus_skew 20.000} {set_bus_skew 4.000}] $timing]
    append timing "\nset_multicycle_path 2 -setup -from \[get_clocks -of_objects \[get_pins -hier -filter {NAME =~ */dc/mmcm/CLKOUT0}\]\] -to \[get_ports {dac_a\[*\] dac_b\[*\]}\]\n"
}
if {$profile ne "target125_250" && $adc_divider!=20} {
    set timing [string map [list \
        {create_clock -name adc_clk_a -period 20.000} "create_clock -name adc_clk_a -period $adc_divider.000" \
        {create_clock -name adc_clk_b -period 20.000} "create_clock -name adc_clk_b -period $adc_divider.000" \
        {set_bus_skew 20.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *ca/gray_reg*}]} "set_bus_skew $adc_divider.000 -from \[get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *ca/gray_reg*}\]" \
        {set_bus_skew 20.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cb/gray_reg*}]} "set_bus_skew $adc_divider.000 -from \[get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cb/gray_reg*}\]"] $timing]
}
set f [open $out/timing.xdc w];puts $f $timing;close $f
foreach name {pins tx1 gpio_pins lcd_pins lcd_timing} {add_files -fileset constrs_1 $root/src/constraints/$name.xdc}
add_files -fileset constrs_1 $out/timing.xdc
set_property PROCESSING_ORDER LATE [get_files [list $root/src/constraints/lcd_timing.xdc $out/timing.xdc]]
update_compile_order -fileset sources_1
set f [open $out/ps_config.txt w]
foreach p [lsort [list_property $ps]] {if {[string match CONFIG.* $p]} {puts $f "$p=[get_property $p $ps]"}};close $f
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
report_timing_summary -report_unconstrained -file $out/timing_summary.rpt
report_utilization -file $out/utilization.rpt
report_drc -file $out/drc.rpt
report_cdc -details -file $out/cdc.rpt
report_bus_skew -file $out/bus_skew.rpt
report_io -file $out/io.rpt
set failed 0
foreach kind {max min} {
    set paths [get_timing_paths -delay_type $kind -max_paths 1]
    if {![llength $paths] || [get_property SLACK $paths] < 0} {set failed 1}
}
if {$failed} {
    set f [open $out/build_status.txt w]
    puts $f "vivado=[version -short]\nprofile=$profile\nsta=failed\nrelease_exported=0";close $f
    error "Static timing check failed: $out/timing_summary.rpt"
}
write_bitstream -force $out/bjt.bit
set hwh $out/vivado/bjt.gen/sources_1/bd/system/hw_handoff/system.hwh
if {![file exists $hwh]} {error "Missing matching HWH"}
file copy -force $hwh $out/bjt.hwh
set f [open $out/build_status.txt w]
puts $f "vivado=[version -short]\nprofile=$profile\nsta=passed\nps_preset_supplied=$ps_preset_supplied";close $f
puts "OVERLAY_BUILD_COMPLETE $profile"
close_project
