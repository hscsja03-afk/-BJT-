# Temporary DDR scratch patterns after boot_probe owns the volatile session.
# No storage access, flash writes or PL changes.
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
foreach pattern {0x00000000 0xffffffff 0x55555555 0xaaaaaaaa 0x000000ff 0xffffff00 0x12345678} {
    mwr 0x01010000 $pattern
    puts "DDR_SCRATCH expected=$pattern read=[mrd -value 0x01010000 4]"
}
puts "DDR_TRAINING_STATUS=[mrd -value 0xf8006054 1]"
disconnect
