# Read-only transport smoke test: download one file into volatile DDR via JTAG.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set profile linux_platform_nanya533
set payload [file normalize "D:/FPGA/WSL/PYNQ-work/pynq-image-custom.ub"]
set init [file join $root build work $profile vivado linux_platform.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
if {![file exists $payload]} {error "Missing JTAG test payload: $payload"}
if {![file exists $init]} {error "Missing PS init: $init"}

connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set boot [mrd -value 0xf800025c 1]
if {$boot != 0} {error "Expected JTAG boot mode 0, got $boot"}
targets -set -filter {name =~ "ARM*#0"}
stop
rst -system
after 1000
source $init
ps7_init
ps7_post_config

dow -data $payload 0x01000000
set first_words [mrd -value 0x01000000 4]
puts "JTAG_DATA_LOAD_BYTES=[file size $payload]"
puts "JTAG_DATA_LOAD_FIRST_WORDS=$first_words"
puts "JTAG_DATA_LOAD_RESULT=PASS"
disconnect
