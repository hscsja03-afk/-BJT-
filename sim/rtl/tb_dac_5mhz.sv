`timescale 1ns/1ps
// Exercise the production generator against an analytical 5 MHz sine.
// LUT phase truncation is allowed up to 202 codes (2*pi*8192/256).
module tb_dac_5mhz;
    reg clk=0, reset_n=0, request=0;
    reg [1:0] mode=0;
    reg [31:0] codes=32'h80008000, step_a=0, step_b=0;
    wire ack;
    wire [15:0] data_a, data_b;
    dac_generator dut(clk,reset_n,request,mode,codes,step_a,step_b,ack,data_a,data_b);
`ifdef ADDA_DAC_DIVIDER
    localparam integer DIVIDER=`ADDA_DAC_DIVIDER;
`elsif ADDA_DAC_100MSPS
    localparam integer DIVIDER=10;
`else
    localparam integer DIVIDER=20;
`endif
    localparam real POINTS=200.0/DIVIDER;
    localparam [31:0] STEP=$rtoi(4294967296.0*DIVIDER/200.0+0.5);
    always #(DIVIDER/2.0) clk=~clk;
    integer i, ideal, error_codes, max_error=0, cycles=0;
    reg [15:0] held_a, held_b;
    real theta;
    initial begin
        #25; reset_n=1;
        @(posedge clk); #1;
        mode=2;step_a=STEP;step_b=STEP;request=1;
        wait(ack===1); #1;
        if(data_a!==16'h8000 || data_b!==16'h8000) $fatal(1,"Commit did not start at midpoint");
        for(i=0;i<10000;i=i+1) begin
            @(negedge clk); #1;
            if((^data_a===1'bx)||(^data_b===1'bx)) $fatal(1,"Unknown output at sample %d",i);
            theta=6.283185307179586*((i*DIVIDER)%200)/200.0;
            ideal=$rtoi(32768.0+8192.0*$sin(theta)+0.5);
            error_codes=$signed({1'b0,data_a})-ideal;
            if(error_codes<0) error_codes=-error_codes;
            if(error_codes>max_error) max_error=error_codes;
            if(error_codes>202 || data_a!==data_b) $fatal(1,"Bad sine sample %d: A=%h B=%h ideal=%d",i,data_a,data_b,ideal);
            if((i*DIVIDER)%200==0) cycles=cycles+1;
            held_a=data_a;held_b=data_b;
            @(posedge clk); #1;
            if(data_a!==held_a || data_b!==held_b) $fatal(1,"Output changed at rising sampling edge");
        end
        // A mode change must flush old sine samples before acknowledging.
        @(posedge clk); #0.1;
        mode=1; codes=32'hA1235BCD; request=~request;
        wait(ack===request); #0.1;
        if(data_a!==16'h8000 || data_b!==16'h8000) $fatal(1,"Commit ack preceded pipeline flush");
        repeat(4) begin
            @(negedge clk); #0.1;
            if(data_a!==16'h5bcd || data_b!==16'ha123) $fatal(1,"Static code or channel mapping after sine commit");
        end
        @(posedge clk); #0.1;
        mode=0; request=~request;
        wait(ack===request); #0.1;
        repeat(4) begin
            if(data_a!==16'h8000 || data_b!==16'h8000) $fatal(1,"Stale static sample after midpoint commit");
            @(negedge clk); #0.1;
        end
        // Reset must mute the digital bus even if the sample clock stops.
        reset_n=0; #0.1;
        if(data_a!==16'h8000 || data_b!==16'h8000 || ack!==0) $fatal(1,"Asynchronous reset did not flush pipeline");
        $display("PASS: pipelined sine-to-static-to-midpoint transitions, independent channels, commit flush and asynchronous reset");
        $display("PASS: production DAC RTL, 10000 samples at 5MHz, %0f points/period, both channels match, rising-edge stability; max analytical-sine error=%0d codes (LUT truncation tolerance202)",POINTS,max_error);
        $finish;
    end
    initial begin #300000; $fatal(1,"Simulation timeout"); end
endmodule
