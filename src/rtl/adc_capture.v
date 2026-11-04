`timescale 1ns/1ps
// Each channel owns its DCO domain. RAM is read only after the done handshake.
// Two channels are independent captures; their first sample is not guaranteed aligned.
module adc_capture #(parameter ADDR_BITS=10)(input sample_clk, input reset_n, input request,
    input [15:0] data, input overrange, output reg done,
    input bus_clk, input [ADDR_BITS-1:0] read_address, output reg [16:0] read_data,
    input [15:0] sample_stride, input [ADDR_BITS:0] sample_count);
    wire request_sync;
    cdc_sync request_cdc(sample_clk,reset_n,request,request_sync);
    reg active, token;
    reg [ADDR_BITS-1:0] index, last_index;
    // Bundled data: bus holds stride stable before request and until done.
    reg [15:0] stride_latched, remaining;
    (* ram_style="block" *) reg [16:0] memory [0:(1<<ADDR_BITS)-1];
    // Separate the RAM write from reset logic to infer true dual-clock block RAM.
    always @(posedge sample_clk)
        if (active && remaining==0) memory[index]<={overrange,data};
    always @(posedge bus_clk) read_data<=memory[read_address];
    // Synchronous reset of BRAM address/enable avoids asynchronous BRAM controls.
    // Old RAM contents are never exposed: done is invalidated until a full capture.
    always @(posedge sample_clk) begin
        if (!reset_n) begin active<=0; token<=0; done<=0; index<=0; last_index<=0; stride_latched<=1; remaining<=0; end
        else if (!active) begin
            if (request_sync != done) begin
                token<=request_sync; index<=0; active<=1; remaining<=0;
                stride_latched<=sample_stride;
                last_index<=sample_count-1'b1;
            end
        end else if (remaining!=0) remaining<=remaining-1'b1;
        else if (index==last_index) begin active<=0; done<=token; end
        else begin index<=index+1'b1; remaining<=stride_latched-1'b1; end
    end
endmodule
