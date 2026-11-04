# Load the board-side UDP eMMC receiver and monitor its verified chunk count.
set root [file normalize [file join [file dirname [info script]] ..]]
set profile linux_platform_nanya533
set out [file join $root build work emmc_network_writer]
set elf [file join $out emmc_network_writer.elf]
set symbols_path [file join $out symbols.txt]
set init [file join $root build work $profile vivado linux_platform.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
set total_sectors 14948352
set chunk_sectors 65536
set block_bytes 512
set total_chunks [expr {($total_sectors + $chunk_sectors - 1) / $chunk_sectors}]
set total_bytes [expr {$total_sectors * $block_bytes}]

foreach f [list $elf $symbols_path $init] {
    if {![file exists $f]} {error "Missing required file: $f"}
}
set symbols [open $symbols_path r]
set symbol_text [read $symbols]
close $symbols
if {![regexp -line {^([0-9a-fA-F]+) [BD] emmc_writer_control$} $symbol_text -> control_hex]} {
    error "eMMC writer control symbol not found"
}
set control [expr 0x$control_hex]
set ready_addr [format "0x%08x" [expr {$control + 4}]]
set done_addr [format "0x%08x" [expr {$control + 28}]]
set status_addr [format "0x%08x" [expr {$control + 32}]]
set network_ready_addr [format "0x%08x" [expr {$control + 56}]]

proc read32 {address} {
    return [lindex [mrd -value $address 1] 0]
}

set connected 0
try {
    connect -url tcp:127.0.0.1:3121
    set connected 1
    targets -set -filter {name =~ "APU"}
    set boot_mode [read32 0xf800025c]
    if {$boot_mode != 0} {error "Expected JTAG boot mode 0, got $boot_mode"}
    targets -set -filter {name =~ "ARM*#0"}
    if {[catch {stop} stop_error] && ![string match -nocase "*Already stopped*" $stop_error]} {
        error "Unable to stop target before reset: $stop_error"
    }
    rst -system
    after 1000
    source $init
    ps7_init
    ps7_post_config
    dow $elf
    con

    set ready 0
    for {set wait 0} {$wait < 600} {incr wait} {
        after 100
        set ready_value [read32 $ready_addr]
        set status [read32 $status_addr]
        set network_ready [read32 $network_ready_addr]
        if {$status == 4} {error "Network eMMC writer failed during initialization"}
        if {$ready_value == 1 && $status == 1 && $network_ready == 1} {set ready 1; break}
    }
    if {!$ready} {error "Network eMMC writer did not become ready"}
    puts "EMMC_NET_READY ip=192.168.0.2 port=5001"

    set last_done 0
    for {set wait 0} {$wait < 7200} {incr wait} {
        after 1000
        set done [read32 $done_addr]
        set status [read32 $status_addr]
        if {$status == 4} {error "Network eMMC writer reported ERROR after $done chunks"}
        if {$done > $last_done} {
            set bytes [expr {min($done * $chunk_sectors * $block_bytes, $total_bytes)}]
            puts "EMMC_NET_PROGRESS chunks=$done/$total_chunks bytes=$bytes/$total_bytes"
            set last_done $done
        }
        if {$done >= $total_chunks} {
            puts "EMMC_IMAGE_WRITE_COMPLETE chunks=$done bytes=$total_bytes"
            break
        }
    }
    if {$last_done < $total_chunks} {error "Network eMMC writer timed out after $last_done chunks"}
} finally {
    if {$connected} {disconnect}
}
