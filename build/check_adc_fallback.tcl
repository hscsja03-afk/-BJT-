# Re-check the routed candidate at its calibrated 50 MHz operating point.
set root [file normalize [file join [file dirname [info script]] ..]]
set candidate [file normalize [lindex $argv 0]]
open_checkpoint $candidate/vivado/bjt.runs/impl_1/adda_dac_gui_top_routed.dcp
foreach c {a b} {create_clock -name adc_clk_$c -period 20.000 [get_ports adc_dco_$c]}
foreach c {aca acb} {
    set_property CLKIN1_PERIOD 20.000 [get_cells -hier -filter "NAME =~ */$c/mmcm"]
}
report_timing_summary -report_unconstrained -file $candidate/timing_50mhz.rpt
report_drc -file $candidate/drc_50mhz.rpt
foreach kind {max min} {
    set path [get_timing_paths -delay_type $kind -max_paths 1]
    if {![llength $path] || [get_property SLACK $path] < 0} {error "50 MHz fallback STA failed"}
}
puts "ADC_50MHZ_FALLBACK_TIMING_PASS"
close_design
