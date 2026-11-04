`timescale 1ns/1ps
// Two banks per channel. The bus can only write the inactive bank while idle.
// Request toggle is also the bank number. Payload remains stable until ACK.
module dac_awg(
    input bus_clk, sample_clk, reset_n,
    input [1:0] request,
    input [31:0] step_a,step_b,phase_a,phase_b,
    input write_a,write_b,bank_a,bank_b,
    input [7:0] write_address,
    input [15:0] write_data,
    output reg [1:0] acknowledge,
    output reg [15:0] data_a,data_b
);
    (* ram_style="block" *) reg [15:0] table_a[0:511];
    (* ram_style="block" *) reg [15:0] table_b[0:511];
    (* ASYNC_REG="TRUE" *) reg [1:0] req_meta,req_sync;
    // Bundled data, sampled only after the two-stage request synchronizer.
    (* ASYNC_REG="TRUE" *) reg [31:0] sa_meta,sa_sync,sb_meta,sb_sync;
    (* ASYNC_REG="TRUE" *) reg [31:0] pa_meta,pa_sync,pb_meta,pb_sync;
    reg [31:0] sa,sb,pa,pb;
    reg [1:0] valid;
    reg [15:0] sample_a,sample_b;
    reg [15:0] ram_pipe_a,ram_pipe_b,qualified_a,qualified_b;
    reg [1:0] valid_a_pipe,valid_b_pipe;
    (* IOB="TRUE" *) reg [15:0] out_a,out_b;
    always @* begin data_a=out_a;data_b=out_b;end
    always @(posedge bus_clk) begin
        if(write_a) table_a[{bank_a,write_address}]<=write_data;
        if(write_b) table_b[{bank_b,write_address}]<=write_data;
    end
    // Unreset read registers allow inference of true dual-port block RAM.
    always @(negedge sample_clk) begin
        sample_a<=table_a[{acknowledge[0],pa[31:24]}];
        sample_b<=table_b[{acknowledge[1],pb[31:24]}];
        ram_pipe_a<=sample_a;ram_pipe_b<=sample_b;
    end
    always @(negedge sample_clk or negedge reset_n) begin
        if(!reset_n) begin out_a<=16'h8000;out_b<=16'h8000;end
        else begin out_a<=qualified_a;out_b<=qualified_b;end
    end
    always @(negedge sample_clk) begin
        if(!reset_n) begin
            req_meta<=0;req_sync<=0;acknowledge<=0;valid<=0;
            sa_meta<=0;sa_sync<=0;sb_meta<=0;sb_sync<=0;
            pa_meta<=0;pa_sync<=0;pb_meta<=0;pb_sync<=0;
            sa<=0;sb<=0;pa<=0;pb<=0;
            qualified_a<=16'h8000;qualified_b<=16'h8000;valid_a_pipe<=0;valid_b_pipe<=0;
        end else begin
            req_meta<=request;req_sync<=req_meta;
            sa_meta<=step_a;sa_sync<=sa_meta;sb_meta<=step_b;sb_sync<=sb_meta;
            pa_meta<=phase_a;pa_sync<=pa_meta;pb_meta<=phase_b;pb_sync<=pb_meta;
            valid_a_pipe<={valid_a_pipe[0],valid[0]};valid_b_pipe<={valid_b_pipe[0],valid[1]};
            qualified_a<=valid_a_pipe[1]?ram_pipe_a:16'h8000;
            qualified_b<=valid_b_pipe[1]?ram_pipe_b:16'h8000;
            pa<=pa+sa;pb<=pb+sb;
            if(req_sync[0]!=acknowledge[0]) begin
                acknowledge[0]<=req_sync[0];sa<=sa_sync;pa<=pa_sync;valid[0]<=1;
            end
            if(req_sync[1]!=acknowledge[1]) begin
                acknowledge[1]<=req_sync[1];sb<=sb_sync;pb<=pb_sync;valid[1]<=1;
            end
        end
    end
endmodule
