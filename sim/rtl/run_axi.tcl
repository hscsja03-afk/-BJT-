# Independent RTL regression; no hardware server or board connection.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set out $root/build/work/axi_sim
file mkdir $out
cd $out
file copy -force $root/src/rtl/sine256.mem $out/sine256.mem
set bin $::env(XILINX_VIVADO)/bin
proc run {args} {
    if {[catch {exec {*}$args 2>@1} result]} {puts $result;error "Simulation command failed"}
    puts $result;return $result
}
set files {}
foreach name {adda_core.v adc_capture.v adc_clocking.v adc_statistics.sv cdc_sync.v dac_clocking.v dac_generator.v dac_awg.v gpio_control.sv} {
    set f [open $root/src/rtl/$name];set data [read $f];close $f
    set dst $out/$name
    set f [open $dst w]
    puts $f "`define ADDA_DAC_GUI\n`define ADDA_GPIO\n`define ADDA_TX1\n`define ADDA_ADC_DIVIDER 16\n`define ADDA_DAC_DIVIDER 4\n`define ADDA_DAC_PHASE 202.5\n$data";close $f
    lappend files $dst
}
set f [open $root/sim/rtl/tb_dac_axi.sv];set data [read $f];close $f
set f [open $out/tb_dac_axi.sv w];puts $f "`define ADDA_DAC_DIVIDER 4\n$data";close $f
lappend files $out/tb_dac_axi.sv
run $bin/xvlog.bat -sv {*}$files
run $bin/xvlog.bat $::env(XILINX_VIVADO)/data/verilog/src/glbl.v
run $bin/xelab.bat tb_dac_axi glbl -s dac_axi_sim -debug typical -L unisims_ver
set log [run $bin/xsim.bat dac_axi_sim -runall]
if {![string match {*PASS GPIO AXI registers*} $log] || ![string match {*PASS: AXI AW/W ordering*} $log] || [string match {*Fatal:*} $log]} {error "AXI regression failed"}
set f [open $out/result.txt w];puts $f "GPIO_AXI_SIMULATION_PASS";close $f
puts "GPIO_AXI_SIMULATION_PASS"
