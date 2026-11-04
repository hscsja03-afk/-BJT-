# Diagnostic follow-up after independent factory SD boot yielded no console.
# Halts ARM0 to inspect registers; no reset/init, download, DDR write or storage.
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
set mode [mrd -value 0xf800025c 1]
if {$mode != 5} {error "Expected the confirmed factory SD boot"}
targets -set -filter {name =~ "ARM*#0"}
stop
puts "FACTORY_STOP_REGISTERS_BEGIN"
puts [rrd]
puts "FACTORY_STOP_REGISTERS_END"
puts "FACTORY_STOP_DONE ARM0 remains halted for inspection"
disconnect
