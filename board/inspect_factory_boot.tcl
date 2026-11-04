# Read-only observation after user-initiated SD boot. No stop/reset/init/download.
connect -url tcp:127.0.0.1:3121
puts "FACTORY_BOOT_TARGETS_BEGIN"
puts [targets]
puts "FACTORY_BOOT_TARGETS_END"
targets -set -filter {name =~ "APU"}
foreach {name address count} {
    BOOT_MODE 0xf800025c 1
    REBOOT_STATUS 0xf8000258 1
    DDR_CTRL 0xf8006000 1
    DDR_MODE 0xf8006054 1
    DEVCFG_STATUS 0xf800700c 1
    MIO14_15 0xf8000738 2
    UART_CLOCK 0xf8000154 1
    UART0_CONTROL_MODE 0xe0000000 2
    UART0_BAUDGEN 0xe0000018 1
    UART0_STATUS 0xe000002c 1
    UART0_BAUDDIV 0xe0000034 1
    OCM_FSBL_PREFIX 0x00000000 64
    DDR_UBOOT_PREFIX 0x04000000 64
    FSBL_DDR_CHECK_CODE 0x0000e31c 12
    FSBL_FAILURE_CALL_CODE 0x0000e468 8
    FSBL_FAILURE_LOOP_CODE 0x000018ac 1
    FSBL_DDR_CHECK_WORD1 0x00100000 1
    FSBL_DDR_CHECK_WORD2 0x00200000 1
} {
    if {[catch {mrd -value $address $count} result]} {
        puts "FACTORY_BOOT_${name}_READ_ERROR=$result"
    } else {
        puts "FACTORY_BOOT_${name}=$result"
    }
}
puts "FACTORY_BOOT_INSPECT_DONE"
disconnect
