# Read-only continuation monitor for a network eMMC writer already running on the board.
set root [file normalize [file join [file dirname [info script]] ..]]
set symbols_path [file join $root build work emmc_network_writer symbols.txt]
set total_sectors 14948352
set chunk_sectors 65536
set block_bytes 512
set total_chunks [expr {($total_sectors + $chunk_sectors - 1) / $chunk_sectors}]
set total_bytes [expr {$total_sectors * $block_bytes}]

if {![file exists $symbols_path]} {error "Missing symbols file: $symbols_path"}
set symbols [open $symbols_path r]
set symbol_text [read $symbols]
close $symbols
if {![regexp -line {^([0-9a-fA-F]+) [BD] emmc_writer_control$} $symbol_text -> control_hex]} {
    error "eMMC writer control symbol not found"
}
set control [expr 0x$control_hex]
set done_addr [format "0x%08x" [expr {$control + 28}]]
set status_addr [format "0x%08x" [expr {$control + 32}]]

proc read32 {address} {
    return [lindex [mrd -value $address 1] 0]
}

set connected 0
try {
    connect -url tcp:127.0.0.1:3121
    set connected 1
    targets -set -filter {name =~ "ARM*#0"}
    set last_done [read32 $done_addr]
    set status [read32 $status_addr]
    if {$status == 4} {error "Network eMMC writer is in ERROR state after $last_done chunks"}
    puts "EMMC_MONITOR_RESUMED chunks=$last_done/$total_chunks"

    for {set wait 0} {$wait < 43200} {incr wait} {
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
    if {$last_done < $total_chunks} {error "Read-only monitor timed out after $last_done chunks"}
} finally {
    if {$connected} {disconnect}
}
