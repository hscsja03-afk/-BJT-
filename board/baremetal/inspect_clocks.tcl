# Read-only inspection of running PS/PL clocks; no reset, halt or writes.
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set saved [configparams force-mem-accesses]
configparams force-mem-accesses 1
foreach {label address count} {
    BOOT 0xf800025c 1
    CLOCK_CONTROL 0xf8000100 16
    PL_ID_CONTROL_STATUS 0x43c00000 13
    MIO7_15 0xf800071c 9
    MIO29_33 0xf8000774 5
    TIMER0 0xf8f00200 3
    COUNTERS0 0x43c00024 3
} {puts "CLOCK_INSPECT_$label=[mrd -value $address $count]"}
after 200
puts "CLOCK_INSPECT_TIMER1=[mrd -value 0xf8f00200 3]"
puts "CLOCK_INSPECT_COUNTERS1=[mrd -value 0x43c00024 3]"
puts "CLOCK_INSPECT_DONE"
configparams force-mem-accesses $saved
disconnect
