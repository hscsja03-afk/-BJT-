set root [file normalize [file join [file dirname [info script]] .. ..]]
set out $root/build/work/lcd_sim
file mkdir $out
cd $out
set bin $::env(XILINX_VIVADO)/bin
proc run {args} {
    if {[catch {exec {*}$args 2>@1} result]} {puts $result; error "LCD simulation failed"}
    puts $result
    return $result
}
run $bin/xvlog.bat -sv $root/src/rtl/lcd_graphics.sv $root/sim/rtl/tb_lcd_graphics.sv
run $bin/xelab.bat tb_lcd_graphics -s lcd_graphics_sim
set log [run $bin/xsim.bat lcd_graphics_sim -runall]
if {![string match {*PASS LCD GRAPHICS*} $log] || [string match {*Fatal:*} $log]} {error "LCD check failed"}
