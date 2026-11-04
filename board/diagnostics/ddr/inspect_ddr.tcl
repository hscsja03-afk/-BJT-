# Read-only follow-up while the temporary OCM diagnostic owns the board.
# No CPU halt/reset, DDR writes, PL download, or storage access.
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
puts "DDR_INSPECT_BOOT=[mrd -value 0xf800025c 1]"
puts "DDR_INSPECT_SILICON=[mrd -value 0xf8007080 1]"
puts "DDR_INSPECT_CTRL=[mrd -value 0xf8006000 1]"
puts "DDR_INSPECT_MODE=[mrd -value 0xf8006054 1]"
puts "DDR_INSPECT_PHY_CONFIG=[mrd -value 0xf8006140 20]"
puts "DDR_INSPECT_TRAINING=[mrd -value 0xf80061a4 12]"
foreach base {0x01000000 0x11000000 0x21000000 0x31000000} {
    puts "DDR_INSPECT_DATA_${base}=[mrd -value $base 64]"
}
puts "DDR_INSPECT_DONE"
disconnect
