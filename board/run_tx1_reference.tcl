# Temporary execution of the unmodified 2026-10-25 archived baremetal image.
# Requires a powered-down Linux followed by a cold boot in JTAG mode.
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/work/tx1_reference_baremetal_20261030
foreach name {reference.bit reference.elf ps7_init.tcl} {
    if {![file isfile $out/$name]} {error "Missing archived artifact: $name"}
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set boot [mrd -value 0xf800025c 1]
puts "TX1_REFERENCE_BOOT_MODE=$boot"
if {($boot & 7)!=0} {error "Cold boot in JTAG mode required before reset"}
targets -set -filter {name =~ "ARM*#0"}
rst -system -stop
after 1000
foreach core {0 1} {
    targets -set -filter [format {name =~ "ARM*#%d"} $core]
    if {![string match "Stopped*" [state]]} {stop -timeout 5000}
    if {![string match "Stopped*" [state]]} {error "ARM core $core not halted"}
}
targets -set -filter {name =~ "xc7z020*"}
fpga -file $out/reference.bit
targets -set -filter {name =~ "ARM*#0"}
source $out/ps7_init.tcl
ps7_init
ps7_post_config
dow $out/reference.elf
con
puts "TX1_REFERENCE_RUNNING original_archive=20261025 flash_written=0"
disconnect
