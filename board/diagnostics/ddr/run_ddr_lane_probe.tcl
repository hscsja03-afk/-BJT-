# Temporary PS restart and volatile DDR pattern writes on ORIGINAL baseboard.
set root [file normalize [file join [file dirname [info script]] .. .. ..]]
set folder [expr {[llength $argv]>1 ? [lindex $argv 1] : "ddr_lane_probe"}]
if {$folder ni {ddr_lane_probe ddr_lane_probe2020}} {error "Unknown ELF folder"}
set out $root/build/work/$folder
set profile [expr {[llength $argv] ? [lindex $argv 0] : "linux_platform"}]
if {$profile ni {linux_platform linux_platform333 linux_platform333_nowl linux_platform2020 linux_platform_nanya533}} {error "Unknown PS profile"}
set init $root/build/work/$profile/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl
foreach f [list $init $out/ddr_lane_probe.elf $out/symbols.txt] {
    if {![file exists $f]} {error "Missing $f"}
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set boot [mrd -value 0xf800025c 1]
if {$boot != 0} {error "Original baseboard must be in JTAG boot mode"}
puts "DDR_LANE_BOARD=official PROFILE=$profile ELF_FOLDER=$folder BOOT_MODE=$boot"
targets -set -filter {name =~ "ARM*#0"}
stop
rst -system
after 1000
targets -set -filter {name =~ "ARM*#0"}
source $init
ps7_init
ps7_post_config
dow $out/ddr_lane_probe.elf
con
after 3000
targets -set -filter {name =~ "APU"}
set f [open $out/symbols.txt];set symbols [read $f];close $f
if {![regexp -line {^([0-9a-fA-F]+) D ddr_lane_result$} $symbols -> address]} {error "Missing result symbol"}
puts "DDR_LANE_RESULT=[mrd -value 0x$address 69]"
puts "DDR_LANE_TRAINING=[mrd -value 0xf80061a4 12]"
puts "DDR_LANE_DONE"
disconnect
