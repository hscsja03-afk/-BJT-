set root [file normalize [file join [file dirname [info script]] ..]]
set dest $root/build/backups/qspi_before_persistence_20261030.bin
if {[file exists $dest]} {error "Refusing to overwrite original QSPI backup"}
file mkdir [file dirname $dest]
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "ARM*#0"}
stop
mrd -bin -file $dest 0x10000000 8388608
con
disconnect
puts "QSPI_BACKUP_SAVED=$dest"
exit
