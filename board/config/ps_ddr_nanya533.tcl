# Diagnostic-only override for user-reported NT5CC256M16ER-EK.
# Source AFTER ps_core_2v5.tcl. Do not replace the production profile until tested.
# Nanya DDR3-4Gb E-die datasheet v1.8 (04/2019): pp. 1, 3, 134, 136, 138.
# At CK=533.333 MHz, CL/tRCD/tRP=8 gives 15 ns, avoiding optional 7-cycle
# down-binning assumptions; CWL=6. x16 has a 2 KiB page, requiring tFAW=50 ns.
# tRAS=35 ns rounds to 19 cycles; tRC=51 ns covers 19+8 cycles (50.625 ns).
# Keep board delays, training, drive strength and peripheral settings unchanged.
set nanya_ddr_settings [list \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {Custom} \
    CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ {533.333333} \
    CONFIG.PCW_UIPARAM_DDR_SPEED_BIN {DDR3_1066G} \
    CONFIG.PCW_UIPARAM_DDR_CL {8} \
    CONFIG.PCW_UIPARAM_DDR_CWL {6} \
    CONFIG.PCW_UIPARAM_DDR_T_RCD {8} \
    CONFIG.PCW_UIPARAM_DDR_T_RP {8} \
    CONFIG.PCW_UIPARAM_DDR_T_RAS_MIN {35.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RC {51.0} \
    CONFIG.PCW_UIPARAM_DDR_T_FAW {50.0}]
set_property -dict $nanya_ddr_settings $ps
foreach {p expected} $nanya_ddr_settings {
    if {[get_property $p $ps] ne $expected} {
        error "Nanya DDR setting was not retained: $p expected $expected, got [get_property $p $ps]"
    }
}
