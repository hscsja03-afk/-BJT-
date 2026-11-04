# TEL/EPRO: U7.6 -> X1.74 -> core X3.27 -> H18 (B35_L14_N)
#          U7.8 -> X1.76 -> core X3.25 -> J18 (B35_L14_P)
set_property PACKAGE_PIN H18 [get_ports tx1_scl]
set_property PACKAGE_PIN J18 [get_ports tx1_sda]
set_property IOSTANDARD LVCMOS33 [get_ports {tx1_scl tx1_sda}]
set_property DRIVE 4 [get_ports {tx1_scl tx1_sda}]
set_property SLEW SLOW [get_ports {tx1_scl tx1_sda}]
# Software I2C imposes >=2us phase waits and samples synchronized inputs.
# No synchronous external clock relation exists for these open-drain pins.
set_false_path -from [get_ports {tx1_scl tx1_sda}]
set_false_path -to [get_ports {tx1_scl tx1_sda}]
