# Temporary diagnostic deployment. Restarts PS, initializes DDR/eMMC MIO, runs
# OCM ELF. It does NOT program PL, QSPI, eMMC content or boot configuration.
set root [file normalize [file join [file dirname [info script]] ..]]
set elf $root/build/work/boot_probe/boot_probe.elf
set ps_dir [expr {[llength $argv] ? [lindex $argv 0] : "linux_platform"}]
set board_kind [expr {[llength $argv] > 1 ? [lindex $argv 1] : "custom"}]
if {$board_kind ni {custom custom_jtag official}} {error "Unknown baseboard kind"}
if {$ps_dir ni {linux_platform linux_platform333 linux_platform333_nowl linux_platform_nanya533}} {error "Unknown PS profile directory"}
set init $root/build/work/$ps_dir/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl
foreach f [list $elf $init] {if {![file exists $f]} {error "Missing $f"}}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set boot [mrd -value 0xf800025c 1]
set expected_boot [expr {$board_kind in {official custom_jtag} ? 0 : 1}]
if {$boot != $expected_boot} {error "Boot mode $boot differs from expected $expected_boot for $board_kind baseboard"}
puts "BOOT_PROBE_BOARD=$board_kind PROFILE=$ps_dir BOOT_MODE=$boot"
targets -set -filter {name =~ "ARM*#0"}
stop
rst -system
after 1000
targets -set -filter {name =~ "ARM*#0"}
source $init
ps7_init
ps7_post_config
dow $elf
con
after 5000
targets -set -filter {name =~ "APU"}
# Result address is printed from the current ELF's symbols, never assumed.
set f [open $root/build/work/boot_probe/symbols.txt];set symbols [read $f];close $f
if {![regexp -line {^([0-9a-fA-F]+) D boot_probe_result$} $symbols -> address]} {error "Probe result symbol not found"}
puts "BOOT_PROBE_RESULT=[mrd -value 0x$address 31]"
disconnect
