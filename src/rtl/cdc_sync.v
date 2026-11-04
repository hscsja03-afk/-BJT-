`timescale 1ns/1ps
module cdc_sync #(parameter WIDTH=1)(input clk, input reset_n,
    input [WIDTH-1:0] din, output [WIDTH-1:0] dout);
    (* ASYNC_REG="TRUE" *) reg [WIDTH-1:0] meta, sync;
    always @(posedge clk or negedge reset_n)
        if (!reset_n) begin meta<=0; sync<=0; end
        else begin meta<=din; sync<=meta; end
    assign dout=sync;
endmodule

module reset_sync #(parameter FALLING=0)(input clk, input arst_n, output reset_n);
    (* ASYNC_REG="TRUE" *) reg [1:0] pipe;
    generate if(FALLING) begin : falling_release
        always @(negedge clk or negedge arst_n)
            if (!arst_n) pipe<=0; else pipe<={pipe[0],1'b1};
    end else begin : rising_release
        always @(posedge clk or negedge arst_n)
            if (!arst_n) pipe<=0; else pipe<={pipe[0],1'b1};
    end endgenerate
    assign reset_n=pipe[1];
endmodule

// A registered Gray counter provides a coherent running clock count across CDC.
module clock_counter(input source_clk, input source_reset_n,
    input bus_clk, input bus_reset_n, output [31:0] count);
    reg [31:0] binary, gray;
    wire [31:0] next_binary=binary+32'd1;
    wire [31:0] gray_sync;
    reg [31:0] decoded;
    integer i;
    always @(posedge source_clk or negedge source_reset_n)
        if (!source_reset_n) begin binary<=0; gray<=0; end
        else begin binary<=next_binary; gray<=next_binary^(next_binary>>1); end
    cdc_sync #(.WIDTH(32)) crossing(bus_clk,bus_reset_n,gray,gray_sync);
    always @* begin
        decoded[31]=gray_sync[31];
        for(i=30;i>=0;i=i-1) decoded[i]=decoded[i+1]^gray_sync[i];
    end
    assign count=decoded;
endmodule
