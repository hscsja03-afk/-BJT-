# Temporary JTAG download. No external DDR initialization or storage writes.
set root [file normalize [file join [file dirname [info script]] ../..]]
if {[llength $argv]!=1 || [lindex $argv 0] ni {original custom}} {error "Specify original or custom baseboard"}
set board [lindex $argv 0]
set mode [expr {$board eq "custom" ? "adda" : "probe"}]
set out $root/build/work/baremetal
set init $root/build/work/baseline50/vivado/bjt.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl
set f [open $out/${mode}_symbols.txt];set symbols [read $f];close $f
if {![regexp -line {^([0-9a-fA-F]+) D bjt_mailbox$} $symbols -> address]} {error "Missing mailbox"}
set mailbox [expr 0x$address]
set f [open $init];set initialization [read $f];close $f
if {[string match *ps7_ddr_init* $initialization] || [regexp -nocase {mask_write\s+0xf8006} $initialization]} {error "DDR initializer forbidden"}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set boot [mrd -value 0xf800025c 1]
if {$boot!=0} {error "JTAG boot required before reset"}
puts "BAREMETAL_BEGIN board=$board boot=$boot mode=$mode"
targets -set -filter {name =~ "ARM*#0"}
stop
rst -system
after 1000
targets -set -filter {name =~ "ARM*#0"}
source $init
ps7_init
if {$board eq "custom"} {
    targets -set -filter {name =~ "xc7z020"}
    fpga -file $root/build/work/baseline50/bjt.bit
    targets -set -filter {name =~ "ARM*#0"}
    ps7_post_config
}
dow $out/$mode.elf
con
after 300
targets -set -filter {name =~ "APU"}
set head [mrd -value $mailbox 14]
if {[lrange $head 0 2] ne [list 1112167473 1 [expr {$board eq "custom"}]]} {error "Unexpected mailbox identity"}
puts "BAREMETAL_HEADER=$head"
proc command {seq op args expected_status} {
    global mailbox
    mwr [expr {$mailbox+24}] $op
    for {set i 0} {$i<4} {incr i} {mwr [expr {$mailbox+28+4*$i}] [lindex $args $i]}
    mwr [expr {$mailbox+16}] $seq
    set done 0
    for {set n 0} {$n<100} {incr n} {
        after 50
        if {[mrd -value [expr {$mailbox+20}] 1]==$seq} {set done 1;break}
    }
    if {!$done} {error "Mailbox command timed out"}
    set h [mrd -value [expr {$mailbox+44}] 3]
    lassign $h status count crc
    if {$count>2048 || $status!=$expected_status} {error "Unexpected command status/length: $h"}
    set values {}
    if {$count} {set values [mrd -value [expr {$mailbox+56}] $count]}
    puts "BAREMETAL_RESPONSE seq=$seq op=$op status=$status count=$count crc=$crc values=$values"
    return $values
}
set ping [command 1 1 {0 0 0 0} 0]
if {[llength $ping]!=7 || [lindex $ping 2]!=0 || [lindex $ping 3]>196608} {error "Invalid OCM/DDR identity"}
set f [open $out/build_id.txt];set buildid [string trim [read $f]];close $f
if {[lindex $ping 6] != [expr 0x$buildid]} {error "Firmware build identity mismatch"}
set test [command 2 9 {0 0 0 0} 0]
if {[llength $test]!=3 || [lrange $test 0 1] ne {4096 0} || [lindex $test 2]>=196608} {error "OCM scratch test failed"}
if {$board eq "original"} {command 3 2 {20 20 0 0} 7}
puts "BAREMETAL_READY board=$board ddr_initialized=0 analog_initialized=0"
disconnect
