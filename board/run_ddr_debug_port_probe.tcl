# Run immediately after the 2020.2 OCM lane probe on the confirmed original
# baseboard in JTAG mode. This uses the APU debug memory access, not CPU code.
# Only 0x01030000..0x010303ff (volatile DDR) is overwritten; no storage or PL.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1 || ![regexp {^[0-9]{8}_[0-9]{6}$} [lindex $argv 0]]} {
    error "Supply a unique YYYYMMDD_HHMMSS output suffix"
}
set prefix $root/build/logs/ddr_dap_official_[lindex $argv 0]
if {[file exists ${prefix}_frames.csv]} {error "Refusing to overwrite earlier evidence"}
set f [open $root/build/work/ddr_lane_probe2020/symbols.txt]
set symbols [read $f]; close $f
if {![regexp -line {^([0-9a-fA-F]+) D ddr_lane_result$} $symbols -> result_address]} {
    error "Missing 2020.2 lane-probe result symbol"
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
if {[mrd -value 0xf800025c 1] != 0} {error "JTAG boot mode required"}
set header [mrd -value 0x$result_address 3]
if {$header ne "1145328177 1 1"} {error "Completed 2020.2 OCM diagnostic required, got $header"}
targets -set -filter {name =~ "ARM*#0"}
stop
targets -set -filter {name =~ "APU"}
puts "DDR_DAP_ACCESS=APU debug port; ARM0 halted; no CPU load/store program"
puts "DDR_DAP_CTRL=[mrd -value 0xf8006000 1]"
puts "DDR_DAP_TRAINING=[mrd -value 0xf80061a4 12]"
set f [open ${prefix}_frames.csv {WRONLY CREAT EXCL}]
puts $f "pattern,pass,address,expected,actual"
set totals {}; set byte_errors {0 0 0 0}; set xor_mask 0
set base 0x01030000
for {set kind 0} {$kind < 8} {incr kind} {
    set expected {}
    for {set i 0} {$i < 256} {incr i} {
        if {$kind < 6} {
            set value [lindex {0 0xffffffff 0x55555555 0xaaaaaaaa 0x00ff00ff 0xff00ff00} $kind]
        } elseif {$kind == 6} {
            set value [expr {($base + 4*$i) ^ 0xa53cc35a}]
        } else {
            set value [expr {(($i + 1) * 0x9e3779b9) & 0xffffffff}]
            set value [expr {($value ^ ($value << 13)) & 0xffffffff}]
            set value [expr {$value ^ ($value >> 17)}]
            set value [expr {($value ^ ($value << 5)) & 0xffffffff}]
        }
        lappend expected [expr {$value & 0xffffffff}]
    }
    mwr -size w $base $expected
    set errors 0; set first "none"
    for {set pass 0} {$pass < 2} {incr pass} {
        set actual [mrd -value $base 256]
        if {[llength $actual] != 256} {close $f; error "Incomplete debug-port read"}
        for {set i 0} {$i < 256} {incr i} {
            set want [lindex $expected $i]; set got [lindex $actual $i]
            set address [expr {$base + 4*$i}]
            puts $f [format "%d,%d,0x%08X,0x%08X,0x%08X" $kind $pass $address $want $got]
            set diff [expr {($want ^ $got) & 0xffffffff}]
            if {!$diff} {continue}
            incr errors
            if {$first eq "none"} {set first [format "0x%08X expected=0x%08X actual=0x%08X" $address $want $got]}
            set xor_mask [expr {$xor_mask | $diff}]
            for {set b 0} {$b < 4} {incr b} {
                if {$diff & (0xff << (8*$b))} {lset byte_errors $b [expr {[lindex $byte_errors $b]+1}]}
            }
        }
    }
    lappend totals $errors
    puts "DDR_DAP_PATTERN=$kind comparisons=512 errors=$errors first=$first"
}
close $f
puts "DDR_DAP_ERRORS=$totals"
puts "DDR_DAP_BYTE_ERRORS=$byte_errors"
puts [format "DDR_DAP_XOR_MASK=0x%08X" $xor_mask]
puts "DDR_DAP_DONE comparisons=4096 raw=${prefix}_frames.csv"
disconnect
