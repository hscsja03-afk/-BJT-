`timescale 1ns/1ps
// External DCO and feedback BUFG: compensate insertion delay before IOB capture.
// A divider-16 build accepts 50..62.5 MHz (MMCM VCO 800..1000 MHz).
module adc_clocking(input dco,reset_n,output sample_clk,output locked);
`ifdef ADDA_ADC_DIVIDER
    localparam real RATIO=1.0*`ADDA_ADC_DIVIDER;
`else
    localparam real RATIO=20.0;
`endif
    wire feedback,feedback_global,clock_raw;
    MMCME2_BASE #(.BANDWIDTH("OPTIMIZED"),.CLKIN1_PERIOD(RATIO),
        .CLKFBOUT_MULT_F(RATIO),.DIVCLK_DIVIDE(1),.CLKOUT0_DIVIDE_F(RATIO),
        .CLKOUT0_PHASE(0.0),.STARTUP_WAIT("FALSE")) mmcm(
        .CLKIN1(dco),.CLKFBIN(feedback_global),.RST(!reset_n),.PWRDWN(1'b0),
        .CLKFBOUT(feedback),.CLKOUT0(clock_raw),.LOCKED(locked));
    BUFG feedback_buffer(.I(feedback),.O(feedback_global));
    BUFG sample_buffer(.I(clock_raw),.O(sample_clk));
endmodule
