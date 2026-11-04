`timescale 1ns/1ps
// Deskew the returned DCO before launching DAC data. A raw IBUF->BUFG clock
// inserts too much delay for the half-cycle output budget, even at 50 MHz.
// The 100 MSPS profile shifts the internal clock 180 degrees: the generator's
// falling-edge IOB launch then aligns with rising returned DCO, after the DAC's
// hold window and with a full DCO period before its next setup deadline.
module dac_clocking(input dco, input reset_n, output clk, output locked);
    wire feedback_raw,feedback,clock_raw;
`ifdef ADDA_DAC_DIVIDER
    localparam real INPUT_PERIOD=`ADDA_DAC_DIVIDER, MULTIPLY=`ADDA_DAC_DIVIDER,
                    DIVIDE=`ADDA_DAC_DIVIDER, PHASE=`ADDA_DAC_PHASE;
`elsif ADDA_DAC_100MSPS
    localparam real INPUT_PERIOD=10.0, MULTIPLY=10.0, DIVIDE=10.0, PHASE=180.0;
`else
    localparam real INPUT_PERIOD=20.0, MULTIPLY=20.0, DIVIDE=20.0, PHASE=0.0;
`endif
    MMCME2_BASE #(.BANDWIDTH("OPTIMIZED"),.CLKIN1_PERIOD(INPUT_PERIOD),
        .DIVCLK_DIVIDE(1),.CLKFBOUT_MULT_F(MULTIPLY),.CLKOUT0_DIVIDE_F(DIVIDE),
        .CLKOUT0_PHASE(PHASE),.STARTUP_WAIT("FALSE")) mmcm (
        .CLKIN1(dco),.CLKFBIN(feedback),.CLKFBOUT(feedback_raw),
        .CLKOUT0(clock_raw),.LOCKED(locked),.PWRDWN(1'b0),.RST(!reset_n));
    BUFG feedback_buf(.I(feedback_raw),.O(feedback));
    BUFG output_buf(.I(clock_raw),.O(clk));
endmodule
