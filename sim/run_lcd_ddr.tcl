set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/work/lcd_ddr_sim
file mkdir $out
file copy -force $root/src/assets/font.mem $out/font.mem
cd $out
set bin $::env(XILINX_VIVADO)/bin
proc run {args} {
    if {[catch {exec {*}$args 2>@1} result]} {puts $result;error "LCD DDR simulation failed"}
    puts $result
    return $result
}
run $bin/xvlog.bat -sv $root/src/rtl/lcd_timing.sv $root/src/rtl/lcd_ddr_reader.sv $root/src/rtl/dac_text.sv $root/sim/tb_lcd_ddr.sv
run $bin/xelab.bat tb_lcd_ddr -s lcd_ddr_sim
set log [run $bin/xsim.bat lcd_ddr_sim -runall]
if {![string match {*PASS LCD DDR*} $log] || [string match {*Fatal:*} $log]} {error "DDR simulation failed"}
