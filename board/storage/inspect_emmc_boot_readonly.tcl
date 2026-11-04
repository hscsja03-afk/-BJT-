# Inspect boot state without stopping a CPU, resetting, or changing memory.
connect -url tcp:127.0.0.1:3121
puts "EMMC_BOOT_TARGETS_BEGIN"
puts [targets]
puts "EMMC_BOOT_TARGETS_END"
targets -set -filter {name =~ "APU"}
foreach {name address count} {
    BOOT_MODE 0xf800025c 1
    REBOOT_STATUS 0xf8000258 1
    DDR_CTRL 0xf8006000 1
    DEVCFG_STATUS 0xf800700c 1
    MIO14_15 0xf8000738 2
    MIO40_53 0xf80007a0 14
    UART_CLOCK 0xf8000154 1
    UART0_CONTROL_MODE 0xe0000000 2
    UART0_BAUDGEN 0xe0000018 1
    UART0_STATUS 0xe000002c 1
    UART0_BAUDDIV 0xe0000034 1
    SD0_PRESENT_STATE 0xe0100024 1
    SD1_PRESENT_STATE 0xe0101024 1
    OCM_PREFIX 0x00000000 64
} {
    if {[catch {mrd -value $address $count} result]} {
        puts "EMMC_BOOT_${name}_READ_ERROR=$result"
    } else {
        puts "EMMC_BOOT_${name}=$result"
    }
}
puts "EMMC_BOOT_READONLY_DONE"
disconnect
