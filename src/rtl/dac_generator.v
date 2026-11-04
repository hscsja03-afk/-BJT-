`timescale 1ns/1ps
// Configuration is a bundled-data CDC. Host keeps it stable until ack returns.
// Output changes on internal-clock falling edges. dac_clocking defines its
// phase relative to returned DCO for each sample-rate profile.
module dac_generator(input clk, input reset_n, input request,
    input [1:0] mode, input [31:0] codes, input [31:0] step_a, step_b,
    output reg ack, (* IOB="TRUE" *) output reg [15:0] data_a, data_b);
    (* ASYNC_REG="TRUE" *) reg req_meta, req_sync;
    reg [1:0] active_mode;
    reg [31:0] active_codes, active_step_a, active_step_b, phase_a, phase_b;
    reg accepted;
    reg [15:0] sample_a, sample_b;
    reg [15:0] sine [0:255];
    initial $readmemh("sine256.mem",sine);
    always @(negedge clk or negedge reset_n) begin
        if (!reset_n) begin req_meta<=0; req_sync<=0; end
        else begin req_meta<=request; req_sync<=req_meta; end
    end
    always @(negedge clk or negedge reset_n) begin
        if (!reset_n) begin
            ack<=0; accepted<=0; active_mode<=0; active_codes<=32'h80008000;
            active_step_a<=0; active_step_b<=0; phase_a<=0; phase_b<=0;
            sample_a<=16'h8000; sample_b<=16'h8000;
            data_a<=16'h8000; data_b<=16'h8000;
        end else begin
            // Keep the final IOB register free of lookup/mode/commit logic.
            // The separate fabric stage can be placed beside its LUTs.
            data_a<=sample_a; data_b<=sample_b;
            // Ack only when the midpoint flush reaches the output registers.
            // The first new sample reaches the pins on the following edge.
            ack<=accepted;
            if (req_sync != accepted) begin
                active_mode<=mode; active_codes<=codes;
                active_step_a<=step_a; active_step_b<=step_b;
                phase_a<=0; phase_b<=0; accepted<=req_sync;
                sample_a<=16'h8000; sample_b<=16'h8000;
            end else begin
                phase_a<=phase_a+active_step_a; phase_b<=phase_b+active_step_b;
                case(active_mode)
                    2'd1: begin sample_a<=active_codes[15:0]; sample_b<=active_codes[31:16]; end
                    2'd2: begin sample_a<=sine[phase_a[31:24]]; sample_b<=sine[phase_b[31:24]]; end
                    2'd3: begin sample_a<=16'h6000+{2'b00,phase_a[31:18]}; sample_b<=16'h6000+{2'b00,phase_b[31:18]}; end
                    default: begin sample_a<=16'h8000; sample_b<=16'h8000; end
                endcase
            end
        end
    end
endmodule
