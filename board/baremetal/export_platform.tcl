# Reuse the already routed baseline; never rebuild or connect to hardware here.
set root [file normalize [file join [file dirname [info script]] ../..]]
if {![string match 2026.1* [version -short]]} {error "Vivado 2026.1 required"}
open_project $root/build/work/baseline50/vivado/bjt.xpr
open_bd_design [get_files system.bd]
if {[get_property CONFIG.PCW_UIPARAM_DDR_ENABLE [get_bd_cells ps7]] != 0} {error "DDR must be disabled"}
file mkdir $root/build/work/baremetal
write_hw_platform -fixed -force -file $root/build/work/baremetal/ocm_platform.xsa
puts "BAREMETAL_XSA_EXPORTED DDR=0"
close_project
