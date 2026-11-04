# JTAG eMMC deployment. Pass image path and dry_run_only (0 or 1).
set root [file normalize [file join [file dirname [info script]] .. ..]]
set image [expr {[llength $argv] > 0 ? [lindex $argv 0] : "D:/FPGA/WSL/PYNQ-work/ZYNQ-7020-2.7.0-emmc-fit.img"}]
set dry_run_only [expr {[llength $argv] > 1 ? [lindex $argv 1] : 1}]
set profile linux_platform_nanya533
set out [file join $root build work emmc_writer]
set elf [file join $out emmc_image_writer.elf]
set symbols_path [file join $out symbols.txt]
set chunk_path [file join $out image_chunk.bin]
set init [file join $root build work $profile vivado linux_platform.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
set buffer_addr 0x01000000
set expected_bytes 7653556224
set chunk_bytes 33554432
set block_bytes 512

foreach f [list $image $elf $symbols_path $init] {
    if {![file exists $f]} {error "Missing required file: $f"}
}
if {[file size $image] != $expected_bytes} {error "Image size differs from audited candidate"}
if {[expr {$expected_bytes % $block_bytes}] != 0} {error "Image is not sector aligned"}
if {$dry_run_only ni {0 1}} {error "dry_run_only must be 0 or 1"}

set symbols [open $symbols_path r]
set symbol_text [read $symbols]
close $symbols
if {![regexp -line {^([0-9a-fA-F]+) [BD] emmc_writer_control$} $symbol_text -> control_hex]} {
    error "eMMC writer control symbol not found"
}
set control [expr 0x$control_hex]
set ready_addr [format "0x%08x" [expr {$control + 4}]]
set command_addr [format "0x%08x" [expr {$control + 8}]]
set operation_addr [format "0x%08x" [expr {$control + 12}]]
set lba_addr [format "0x%08x" [expr {$control + 16}]]
set count_addr [format "0x%08x" [expr {$control + 20}]]
set sequence_addr [format "0x%08x" [expr {$control + 24}]]
set done_addr [format "0x%08x" [expr {$control + 28}]]
set status_addr [format "0x%08x" [expr {$control + 32}]]
set expected_crc_addr [format "0x%08x" [expr {$control + 36}]]
set actual_crc_addr [format "0x%08x" [expr {$control + 40}]]
set capacity_addr [format "0x%08x" [expr {$control + 44}]]
set error_addr [format "0x%08x" [expr {$control + 48}]]

proc read32 {address} {
    return [lindex [mrd -value $address 1] 0]
}

proc write_chunk_file {path data} {
    set file [open $path w]
    fconfigure $file -translation binary -encoding binary
    puts -nonewline $file $data
    close $file
}

proc send_chunk {sequence operation lba blocks expected_crc data chunk_path buffer_addr addresses} {
    set command_addr [dict get $addresses command]
    set operation_addr [dict get $addresses operation]
    set lba_addr [dict get $addresses lba]
    set count_addr [dict get $addresses count]
    set sequence_addr [dict get $addresses sequence]
    set done_addr [dict get $addresses done]
    set status_addr [dict get $addresses status]
    set expected_crc_addr [dict get $addresses expected_crc]
    set actual_crc_addr [dict get $addresses actual_crc]
    set error_addr [dict get $addresses error]
    write_chunk_file $chunk_path $data
    targets -set -filter {name =~ "ARM*#0"}
    stop
    dow -data $chunk_path $buffer_addr
    mwr $command_addr 0
    mwr $operation_addr $operation
    mwr $lba_addr $lba
    mwr $count_addr $blocks
    mwr $sequence_addr $sequence
    mwr $expected_crc_addr $expected_crc
    mwr $command_addr 1
    con
    for {set wait 0} {$wait < 9000} {incr wait} {
        after 100
        set done [read32 $done_addr]
        set status [read32 $status_addr]
        if {$done == $sequence} {
            if {$status != 3} {
                set error_code [read32 $error_addr]
                error "Writer rejected sequence $sequence with status $status error $error_code"
            }
            set actual_crc [read32 $actual_crc_addr]
            if {$actual_crc != $expected_crc} {
                error "Target CRC mismatch at LBA $lba: expected $expected_crc got $actual_crc"
            }
            return
        }
        if {$status == 4} {
            set error_code [read32 $error_addr]
            error "Writer failed sequence $sequence with error $error_code"
        }
    }
    error "Writer timed out on sequence $sequence at LBA $lba"
}

set addresses [dict create \
    command $command_addr operation $operation_addr lba $lba_addr count $count_addr \
    sequence $sequence_addr done $done_addr status $status_addr expected_crc $expected_crc_addr \
    actual_crc $actual_crc_addr error $error_addr]
set connected 0
try {
    connect -url tcp:127.0.0.1:3121
    set connected 1
    targets -set -filter {name =~ "APU"}
    set boot_mode [read32 0xf800025c]
    if {$boot_mode != 0} {error "Expected JTAG boot mode 0 while writing, got $boot_mode"}
    targets -set -filter {name =~ "ARM*#0"}
    stop
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
        set initial_status [read32 $status_addr]
        if {$ready_value == 1 && $initial_status != 0} {set ready 1; break}
    }
    if {!$ready} {error "eMMC writer did not become ready"}
    set sectors [read32 $capacity_addr]
    if {$sectors != 15269888} {error "Unexpected eMMC capacity: $sectors sectors"}
    if {[read32 $status_addr] != 1} {
        set error_code [read32 $error_addr]
        error "eMMC writer initialization failed, error $error_code"
    }
    puts "EMMC_WRITER_READY sectors=$sectors"

    set image_file [open $image r]
    fconfigure $image_file -translation binary -encoding binary
    set first_data [read $image_file $chunk_bytes]
    if {[string length $first_data] != $chunk_bytes} {error "Short read in dry-run chunk"}
    set first_crc [expr {[zlib crc32 $first_data] & 0xffffffff}]
    set first_blocks [expr {$chunk_bytes / $block_bytes}]
    send_chunk 1 1 0 $first_blocks $first_crc $first_data $chunk_path $buffer_addr $addresses
    puts "EMMC_DRY_RUN_PASS bytes=$chunk_bytes crc32=[format %08x $first_crc] storage_written=0"
    unset first_data
    if {$dry_run_only == 1} {
        close $image_file
        puts "EMMC_IMAGE_WRITE_SKIPPED dry_run_only=1"
    } else {
        seek $image_file 0
        set total_sectors [expr {$expected_bytes / $block_bytes}]
        set lba 0
        set sequence 2
        while {$lba < $total_sectors} {
            set blocks [expr {min($chunk_bytes / $block_bytes, $total_sectors - $lba)}]
            set bytes [expr {$blocks * $block_bytes}]
            set data [read $image_file $bytes]
            if {[string length $data] != $bytes} {error "Short image read at LBA $lba"}
            set crc [expr {[zlib crc32 $data] & 0xffffffff}]
            send_chunk $sequence 2 $lba $blocks $crc $data $chunk_path $buffer_addr $addresses
            puts "EMMC_IMAGE_WRITE_OK seq=$sequence lba=$lba sectors=$blocks crc32=[format %08x $crc]"
            unset data
            incr lba $blocks
            incr sequence
        }
        close $image_file
        puts "EMMC_IMAGE_WRITE_COMPLETE sectors=$total_sectors bytes=$expected_bytes"
    }
} finally {
    if {$connected} {disconnect}
}
