# Independent version-control experiment using Vivado 2020.2.
# Generates files only; no debug connection or board programming.
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/work/linux_platform2020
file mkdir $out
puts "CONTROL_VIVADO_VERSION=[version -short]"
if {![string match 2020.2* [version -short]]} {error "This comparison requires Vivado 2020.2"}
create_project linux_platform $out/vivado -part xc7z020clg400-2 -force
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
source $root/board/ps_core_2v5.tcl
set_property CONFIG.PCW_USE_M_AXI_GP0 {0} $ps
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} $ps
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
write_hw_platform -fixed -force -file $out/core_2v5.xsa
puts "CONTROL_2020_PS_GENERATED"
close_project
