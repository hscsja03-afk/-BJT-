set root [file normalize [file join [file dirname [info script]] .. ..]]
set backup $root/build/backups/qspi_before_persistence_20261030.bin
if {![file exists $backup] || [file size $backup] != 33554432} {error "Complete QSPI backup required"}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "ARM*#0"}
stop
dow -data $root/build/work/pynq_jtag_boot/BOOT-qspi-candidate.BIN 0x14000000
con
disconnect
puts "QSPI_CANDIDATE_STAGED_IN_RAM_ONLY"
exit
