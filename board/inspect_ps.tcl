# XSDB: read-only debug-target and SLCR inspection, no CPU stop or reset.
connect -url tcp:127.0.0.1:3121
puts [targets]
set apu [targets -target-properties -filter {name =~ "APU"}]
if {[llength $apu]} {
    targets -set -filter {name =~ "APU"}
    foreach {name address} {boot_mode 0xf800025c reboot_status 0xf8000258 ddr_ctrl 0xf8006000 mio46 0xf80007b8 mio47 0xf80007bc mio48 0xf80007c0 mio49 0xf80007c4 mio50 0xf80007c8 mio51 0xf80007cc} {
        puts "READONLY_$name=[mrd -value $address 1]"
    }
} else {
    puts "No APU target selected; no memory access performed"
}
disconnect
