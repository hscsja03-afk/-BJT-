# Generate a separate boot-platform candidate. No existing PL/Flash is touched.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set profile [expr {[llength $argv] ? [lindex $argv 0] : "default"}]
if {$profile ni {default ddr333 ddr333_nowl nanya533}} {error "Unknown PS profile"}
set folder [dict get {default linux_platform ddr333 linux_platform333 ddr333_nowl linux_platform333_nowl nanya533 linux_platform_nanya533} $profile]
set out $root/build/work/$folder
file mkdir $out
create_project linux_platform $out/vivado -part xc7z020clg400-2 -force
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
source $root/board/config/ps_core_2v5.tcl
if {$profile eq "nanya533"} {source $root/board/config/ps_ddr_nanya533.tcl}
if {$profile in {ddr333 ddr333_nowl}} {set_property CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ {333.333333} $ps}
if {$profile eq "ddr333_nowl"} {set_property CONFIG.PCW_UIPARAM_DDR_TRAIN_WRITE_LEVEL {0} $ps}
set_property CONFIG.PCW_USE_M_AXI_GP0 {0} $ps
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} $ps
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
set f [open $out/ps_config.txt w]
foreach p [lsort [list_property $ps]] {if {[string match CONFIG.* $p]} {puts $f "$p=[get_property $p $ps]"}};close $f
write_hw_platform -fixed -force -file $out/core_2v5.xsa
write_bd_tcl -force $out/system_bd.tcl
puts "LINUX_PLATFORM_CANDIDATE_GENERATED: DDR/eMMC not hardware tested"
close_project
