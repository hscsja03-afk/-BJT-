set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build/work/adc_depth_sim
file mkdir $out
cd $out
set bin $::env(XILINX_VIVADO)/bin
proc run {args} {
    if {[catch {exec {*}$args 2>@1} result]} {puts $result;error "ADC depth simulation failed"}
    puts $result;return $result
}
run $bin/xvlog.bat -sv $root/src/rtl/cdc_sync.v $root/src/rtl/adc_capture.v $root/sim/tb_adc_depth.sv
run $bin/xelab.bat tb_adc_depth -s adc_depth_sim -debug typical
set log [run $bin/xsim.bat adc_depth_sim -runall]
if {![string match {*PASS ADC depths*} $log] || [string match {*Fatal:*} $log]} {error "ADC depth regression failed"}
