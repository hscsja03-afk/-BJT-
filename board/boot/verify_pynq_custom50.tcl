set root [file normalize [file join [file dirname [info script]] .. ..]]
if {[llength $argv] != 1} {error "Pass the routed PYNQ custom50 bitstream"}
set bit [file normalize [lindex $argv 0]]
if {![file exists $bit]} {error "Missing bitstream: $bit"}

connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "xc7z020"}
fpga -file $bit
after 500

targets -set -filter {name =~ "APU"}
set saved_force [configparams force-mem-accesses]
configparams force-mem-accesses 1
try {
    set adda_id [mrd -value 0x43c00000 1]
    set snapshot_words [mrd -value 0x43c00020 1]
    set tx1_id [mrd -value 0x43c00044 1]
    set gpio_id [mrd -value 0x43c00048 1]
    set awg_id [mrd -value 0x43c00080 1]
    set dac_rate [mrd -value 0x43c00030 1]
    if {$adda_id != 0x41444441 || $snapshot_words != 1024 ||
        $tx1_id != 0x54583101 || $gpio_id != 0x47504901 ||
        $awg_id != 0x41574701 || $dac_rate != 50000000} {
        error [format "PL readback mismatch: adda=%08X words=%d tx1=%08X gpio=%08X awg=%08X dac_rate=%d" \
            $adda_id $snapshot_words $tx1_id $gpio_id $awg_id $dac_rate]
    }
} finally {
    configparams force-mem-accesses $saved_force
}
puts [format "PYNQ_CUSTOM50_PL_PASS adda=%08X words=%d tx1=%08X gpio=%08X awg=%08X dac_rate=%d" \
    $adda_id $snapshot_words $tx1_id $gpio_id $awg_id $dac_rate]
disconnect
