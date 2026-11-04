# Change only the OCM application. Keep working PS initialization and PL.
set root [file normalize [file join [file dirname [info script]] ../..]]
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
configparams force-mem-accesses 1
if {([mrd -value 0xf800025c 1]&7)!=0} {error "Expected JTAG baremetal state"}
puts "ISOLATION_PL_ID=[mrd -value 0x43c00044 1]"
targets -set -filter {name =~ "ARM*#0"}
stop -timeout 5000
if {![string match "Stopped*" [state]]} {error "Core not halted"}
rst -processor
dow $root/build/work/tx1_reference_baremetal_20261030/isolation.elf
con
puts "ISOLATION_LOADED ps_reset=0 pl_replaced=0"
disconnect
