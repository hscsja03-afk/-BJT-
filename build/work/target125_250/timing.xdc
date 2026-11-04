# Default 50 MSPS profile. create_project.tcl generates a literal 100 MSPS
# DAC variant of this file; XDC does not support conditional Tcl commands.
create_clock -name adc_clk_a -period 8.000 [get_ports adc_dco_a]
create_clock -name adc_clk_b -period 8.000 [get_ports adc_dco_b]
create_clock -name dac_clk -period 4.000 [get_ports dac_dco]
create_clock -name dac_capture -period 4.000 -waveform {1.600 3.600}
# Actual PCB uses MRCC N (U10) for single-ended ADC A DCO. Only this input
# needs fabric routing to BUFG. This is a 50 MHz bring-up workaround, not
# qualification for 125 MSPS. Preferred board change: swap X2.27 and X2.29
# (ORA and DCOA) and regenerate the pin map for the modified hardware.
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets {adc_dco_a_IBUF}]
# AD9268 CMOS changes data around DCO falling edge; capture rising edge.
# AD9268 tSKEW=-0.6..0 ns; AVC16T245 A->B=0.5..3.3 ns;
# AVC4T774 A->B=0.4..4.2 ns (including OR lines). Conservative combined
# envelope: -0.6+0.4-4.2-1.0=-5.4 ns; 0+4.2-0.4+1.0=4.8 ns.
# The +/-1 ns PCB skew budget and TI test loading remain board assumptions.
set_input_delay -clock adc_clk_a -clock_fall -min -5.400 [get_ports {adc_a[*] adc_or_a}]
set_input_delay -clock adc_clk_a -clock_fall -max  4.800 [get_ports {adc_a[*] adc_or_a}]
set_input_delay -clock adc_clk_b -clock_fall -min -5.400 [get_ports {adc_b[*] adc_or_b}]
set_input_delay -clock adc_clk_b -clock_fall -max  4.800 [get_ports {adc_b[*] adc_or_b}]
set_clock_uncertainty 0.200 [get_clocks -include_generated_clocks {adc_clk_a adc_clk_b dac_clk dac_capture}]
# Referenced to returned DCO: max = 2.8 ns tDCO + 0.4 ns setup + 1.3 ns route budget.
# min = 2.0 ns tDCO - 1.2 ns hold + 0 ns minimum round-trip board delay.
set_output_delay -clock dac_capture -max 2.100 [get_ports {dac_a[*] dac_b[*]}]
set_output_delay -clock dac_capture -min -1.600 [get_ports {dac_a[*] dac_b[*]}]
# ADC snapshot RAM is frozen before PS reads; DAC settings use request/ack CDC.
set_clock_groups -asynchronous -group [get_clocks adc_clk_a] -group [get_clocks adc_clk_b] -group [get_clocks -include_generated_clocks {dac_clk dac_capture}] -group [get_clocks -include_generated_clocks clk_fpga_0]
set_false_path -from [get_ports {clkgen_ld clkgen_status clkgen_refmon}]
set_false_path -to [get_ports {clkgen_reset_n clkgen_sync_n}]
# Registered Gray counters must arrive within one source period at first CDC stage.
set_bus_skew 4.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *ca/gray_reg*}] -to [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *ca/crossing/meta_reg*}]
set_bus_skew 4.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cb/gray_reg*}] -to [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cb/crossing/meta_reg*}]
set_bus_skew 4.000 -from [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cd/gray_reg*}] -to [get_cells -hier -filter {IS_SEQUENTIAL == 1 && NAME =~ *cd/crossing/meta_reg*}]

set_multicycle_path 2 -setup -from [get_clocks clock_raw] -to [get_ports {dac_a[*] dac_b[*]}]

