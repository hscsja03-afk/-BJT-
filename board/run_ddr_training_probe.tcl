# Bounded lane-0 automatic-training start-point experiment, not an eye scan.
# Only PHY_INIT_RATIO0 (0xF800612C) changes from the audited Nanya533 init.
# No PL download or persistent-storage access. Original board/JTAG required.
set root [file normalize [file join [file dirname [info script]] ..]]
set init $root/build/work/linux_platform_nanya533/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl
set elf $root/build/work/ddr_lane_probe/ddr_lane_probe.elf
set symbols_file $root/build/work/ddr_lane_probe/symbols.txt
if {[llength $argv] != 1 || [lindex $argv 0] ni {--validate-only --run}} {
    error "Use --validate-only or --run through the PowerShell wrapper"
}
source $init
set original_body [info body ps7_ddr_init_data_3_0]
set original_line {mask_write 0XF800612C 0x000FFFFF 0x00029000}
if {[llength [split [string map [list $original_line @] $original_body] @]] != 2} {
    error "Expected exactly one known lane-0 initial-ratio write"
}
# Ratio units: 1/256 clock. Starting values, not measured PCB delays.
# Gate baseline 164, +/-64. Write-level baseline 0, plus64 and plus128.
set trials {{164 0} {164 64} {164 128} {100 0} {100 64} {100 128} {228 0} {228 64} {228 128}}
proc select_start {gate wr} {
    global original_body original_line
    if {$gate ni {100 164 228} || $wr ni {0 64 128}} {error "Unapproved training start"}
    set value [expr {($gate << 10) | $wr}]
    set line [format "mask_write 0XF800612C 0x000FFFFF 0x%08X" $value]
    proc ps7_ddr_init_data_3_0 {} [string map [list $original_line $line] $original_body]
    return $value
}
if {[lindex $argv 0] eq "--validate-only"} {
    # Execute only the DDR init body against recording stubs; never connect.
    proc mask_write {addr mask value} {
        lappend ::recorded [list [expr {$addr}] [expr {$mask}] [expr {$value}]]
    }
    proc mask_poll {args} {}
    set recorded {}; ps7_ddr_init_data_3_0; set baseline $recorded
    if {[llength $baseline] != 80} {error "Unexpected baseline DDR write count"}
    foreach trial $trials {
        lassign $trial gate wr
        set expected [select_start $gate $wr]
        set recorded {}; ps7_ddr_init_data_3_0
        if {[llength $recorded] != [llength $baseline]} {error "Write count changed"}
        set differences 0
        foreach old $baseline new $recorded {
            if {$old ne $new} {
                incr differences
                if {[lindex $new 0] != 0xf800612c || [lindex $new 1] != 0xfffff || [lindex $new 2] != $expected} {
                    error "Unexpected register mutation"
                }
            }
        }
        if {$differences != ($expected != 0x29000)} {error "Unexpected difference count"}
        puts "TRAINING_VALIDATE gate=$gate write=$wr changed_registers=$differences"
    }
    puts "TRAINING_VALIDATION_DONE cases=9 hardware_connected=0"
    exit
}
set f [open $symbols_file]; set symbols [read $f]; close $f
if {![regexp -line {^([0-9a-fA-F]+) D ddr_lane_result$} $symbols -> result_address]} {
    error "Missing OCM result symbol"
}
proc run_case {id gate wr} {
    global elf result_address
    targets -set -filter {name =~ "APU"}
    if {[mrd -value 0xf800025c 1] != 0} {error "JTAG boot required"}
    set value [select_start $gate $wr]
    puts "TRAINING_CASE_BEGIN id=$id gate=$gate write=$wr init=[format %08X $value]"
    targets -set -filter {name =~ "ARM*#0"}
    stop
    rst -system
    after 1000
    targets -set -filter {name =~ "ARM*#0"}
    ps7_init
    ps7_post_config
    targets -set -filter {name =~ "APU"}
    set starts [mrd -value 0xf800612c 4]
    if {$starts ne [list $value 167936 167936 167936]} {error "Initial ratio readback mismatch: $starts"}
    targets -set -filter {name =~ "ARM*#0"}
    dow $elf
    con
    after 3000
    targets -set -filter {name =~ "APU"}
    set result [mrd -value 0x$result_address 69]
    if {[llength $result] != 69 || [lrange $result 0 2] ne {1145328177 1 1}} {
        error "OCM test did not complete"
    }
    puts "TRAINING_CASE_RESULT id=$id values=$result"
    puts "TRAINING_CASE_RATIOS id=$id values=[mrd -value 0xf80061b8 4]"
    puts "TRAINING_CASE_STATUS id=$id reg2c=[mrd -value 0xf80060b0 1] mode=[mrd -value 0xf8006054 1]"
    puts "TRAINING_CASE_DONE id=$id"
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
if {[mrd -value 0xf800025c 1] != 0} {error "JTAG boot required before any reset"}
if {([mrd -value 0xf8007080 1] >> 28) != 3} {error "Expected previously observed silicon revision 3"}
set failed [catch {
    set id 0
    foreach trial $trials {
        lassign $trial gate wr
        run_case $id $gate $wr
        incr id
    }
} message]
if {$failed} {puts "TRAINING_EXPERIMENT_ABORTED=$message"}
# Restore the exact audited baseline init, then verify it with the same test.
set restore_failed [catch {run_case RESTORE 164 0} restore_message]
if {$restore_failed} {puts "TRAINING_RESTORE_FAILED=$restore_message"} else {puts "TRAINING_BASELINE_RESTORED"}
disconnect
if {$failed || $restore_failed} {error "Training experiment incomplete; inspect log"}
puts "TRAINING_EXPERIMENT_DONE cases=9 restored=1"
