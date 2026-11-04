# FCLK0=50 MHz is shared by ADDA AXI and the display pixel domain.
create_generated_clock -name lcd_forwarded_clk -source [get_pins {system_i/ps7/inst/PS7_i/FCLKCLK[0]}] -divide_by 1 [get_ports lcd_clk]
# The copied touch I2C controller toggles dri_clk every 50 FCLK cycles.
create_generated_clock -name touch_dri_clk -source [get_pins {system_i/ps7/inst/PS7_i/FCLKCLK[0]}] -divide_by 100 [get_pins u_lcd/u_touch_top/u_i2c_dri/dri_clk_reg/Q]
# EK79001 default falling-edge sampling, retaining the old 5 ns setup/hold budget.
set_output_delay -clock lcd_forwarded_clk -clock_fall -max 5.000 [get_ports {lcd_de lcd_rgb[*]}]
set_output_delay -clock lcd_forwarded_clk -clock_fall -min -5.000 [get_ports {lcd_de lcd_rgb[*]}]
set_property DRIVE 8 [get_ports {lcd_rgb[*] lcd_de lcd_clk}]
set_property SLEW FAST [get_ports {lcd_rgb[*] lcd_de lcd_clk}]
# Stable multi-cycle event bus qualified by a synchronized toggle.
set_false_path -to [get_pins -quiet -hier -filter {NAME =~ *u_touch_cdc/toggle_meta_reg/D}]
set_false_path -to [get_pins -quiet -hier -filter {NAME =~ *u_touch_cdc/data_meta_reg*/D}]
# I2C is sampled by the slow divided controller. Board RC/bus timing not qualified.
set_input_delay -clock touch_dri_clk -max 100.000 [get_ports touch_sda]
set_input_delay -clock touch_dri_clk -min 0.000 [get_ports touch_sda]
set_output_delay -clock touch_dri_clk -max 100.000 [get_ports {touch_sda touch_scl touch_rst_n touch_int}]
set_output_delay -clock touch_dri_clk -min 0.000 [get_ports {touch_sda touch_scl touch_rst_n touch_int}]
