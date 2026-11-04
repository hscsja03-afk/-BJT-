# Read-only enumeration. No FPGA download, reset, stop, memory write or flash.
open_hw_manager
connect_hw_server -url localhost:3121
set targets [get_hw_targets]
puts "READONLY_TARGET_COUNT=[llength $targets]"
foreach target $targets {
    current_hw_target $target
    open_hw_target
    foreach device [get_hw_devices] {
        puts "READONLY_DEVICE=$device PART=[get_property PART $device]"
    }
    close_hw_target
}
disconnect_hw_server
close_hw_manager
