# DDR/eMMC/Ethernet settings for the custom ADDA carrier and PYNQ boot path.
# This PS configuration is separately tested on the connected custom carrier.
source [file join [file dirname [info script]] ps_core_2v5.tcl]
source [file join [file dirname [info script]] ps_ddr_nanya533.tcl]

foreach {property expected} {
    CONFIG.PCW_UIPARAM_DDR_ENABLE 1
    CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ 533.333333
    CONFIG.PCW_UIPARAM_DDR_T_FAW 50.0
    CONFIG.PCW_SD1_PERIPHERAL_ENABLE 1
    CONFIG.PCW_UART0_PERIPHERAL_ENABLE 1
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE 1
    CONFIG.PCW_USB0_PERIPHERAL_ENABLE 0
} {
    if {[get_property $property $ps] ne $expected} {
        error "PYNQ PS setting mismatch: $property expected $expected, got [get_property $property $ps]"
    }
}
