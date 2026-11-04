# Caller must have confirmed all outputs disabled. Keep PS and application.
set root [file normalize [file join [file dirname [info script]] ../..]]
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
configparams force-mem-accesses 1
if {([mrd -value 0xf800025c 1]&7)!=0} {error "Expected baremetal JTAG state"}
puts "PS_FCLK_BEFORE=[mrd -value 0xf8000170 4]"
targets -set -filter {name =~ "ARM*#0"}
stop -timeout 5000
if {![string match "Stopped*" [state]]} {error "Core not halted"}
targets -set -filter {name =~ "xc7z020*"}
fpga -file $root/build/work/pynq_custom50/bjt.bit
targets -set -filter {name =~ "APU"}
puts "PS_FCLK_AFTER=[mrd -value 0xf8000170 4]"
puts "NEW_PL_ID=[mrd -value 0x43c00044 1]"
targets -set -filter {name =~ "ARM*#0"}
con
puts "ISOLATION_NEW_PL_RUNNING ps_reset=0 application_replaced=0"
disconnect
