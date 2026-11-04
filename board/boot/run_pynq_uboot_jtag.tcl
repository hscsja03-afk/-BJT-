# Custom ADDA carrier only. Writes volatile RAM/PS registers; does not program flash or PL.
proc stop_if_running {} {
    if {[catch {stop} result] && ![string match "*Already stopped*" $result]} {
        error $result
    }
}
proc main {} {
set root [file normalize [file join [file dirname [info script]] .. ..]]
set init $root/build/work/pynq_custom50/vivado/bjt.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl
set uboot $root/build/work/pynq_jtag_boot/u-boot-verified.bin
set dtb D:/FPGA/WSL/PYNQ-work/u-boot-system-custom.dtb
foreach f [list $init $uboot $dtb] {if {![file exists $f]} {error "Missing $f"}}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set mode [mrd -value 0xf800025c 1]
if {($mode & 7) != 0} {error "Expected JTAG mode, found $mode"}
puts "PYNQ_JTAG_BOOT_MODE=$mode"
targets -set -filter {name =~ "ARM*#0"}
stop_if_running
rst -system
after 1000
targets -set -filter {name =~ "ARM*#0"}
stop_if_running
uplevel #0 [list source $init]
ps7_init
ps7_post_config
dow -data $uboot 0x04000000
dow -data $dtb 0x00100000
if {[mrd -value 0x04000000 1] != 0xea0000b8} {error "U-Boot entry readback mismatch"}
if {[mrd -value 0x00100000 1] != 0xedfe0dd0} {error "Device tree magic readback mismatch"}
rwr pc 0x04000000
con
puts "PYNQ_JTAG_UBOOT_STARTED"
disconnect
}
if {[catch {main} result options]} {
    puts stderr $result
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
exit 0
