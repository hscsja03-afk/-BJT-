# X1.87 -> X3.14 -> F20; R40 -> U18.2
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[0]}]
# X1.85 -> X3.16 -> F19; R39 -> U18.4
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[1]}]
# X1.83 -> X3.18 -> D20; R38 -> U18.6
set_property -dict {PACKAGE_PIN D20 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[2]}]
# X1.81 -> X3.20 -> D19; R37 -> U18.8
set_property -dict {PACKAGE_PIN D19 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[3]}]
# X1.79 -> X3.22 -> C20; R36 -> U18.10
set_property -dict {PACKAGE_PIN C20 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[4]}]
# X1.77 -> X3.24 -> B20; R35 -> U18.12
set_property -dict {PACKAGE_PIN B20 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[5]}]
# X1.48 -> X3.53 -> K16; R41 -> U18.14
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33 DRIVE 4 SLEW SLOW} [get_ports {ext_gpio[6]}]
# Static asynchronous GPIO: no external receiver clock or synchronous timing contract.
set_false_path -to [get_ports {ext_gpio[*]}]
set_false_path -from [get_ports {ext_gpio[*]}] -to [get_pins -hier -filter {NAME =~ *sense_meta_reg*/D}]
