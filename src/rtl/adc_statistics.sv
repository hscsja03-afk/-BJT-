`timescale 1ns/1ps
// Streaming DC/RMS statistics for long AC windows without a large sample RAM.
module adc_statistics(
    input bus_clk, sample_clk, reset_n,
    input request_toggle,
    input [15:0] requested_samples,
    input [15:0] data,
    input overrange,
    output reg done_toggle,
    output reg signed [31:0] sum_centered,
    output reg [47:0] sumsq_centered,
    output reg [31:0] fault_count
);
    wire request_sync;
    cdc_sync request_cdc(sample_clk, reset_n, request_toggle, request_sync);
    (* ASYNC_REG="TRUE" *) reg [15:0] samples_meta, samples_sync;
    reg [15:0] target_samples, sample_index;
    reg active, token;
    reg signed [31:0] sum_accumulator;
    reg [47:0] square_accumulator;
    reg [31:0] fault_accumulator;
    reg signed [16:0] sample_centered_reg;
    reg [31:0] sample_square_reg;
    reg sample_fault_reg, sample_valid_reg, sample_last_reg;
    wire signed [16:0] sample_centered = $signed({1'b0, data}) - 17'sd32768;
    wire signed [33:0] sample_product = sample_centered * sample_centered;
    wire sample_fault = overrange || data == 16'h0000 || data == 16'hffff;

    always @(posedge sample_clk) begin
        if (!reset_n) begin
            samples_meta <= 0;
            samples_sync <= 0;
            target_samples <= 0;
            sample_index <= 0;
            active <= 0;
            token <= 0;
            done_toggle <= 0;
            sum_accumulator <= 0;
            square_accumulator <= 0;
            fault_accumulator <= 0;
            sample_centered_reg <= 0;
            sample_square_reg <= 0;
            sample_fault_reg <= 0;
            sample_valid_reg <= 0;
            sample_last_reg <= 0;
            sum_centered <= 0;
            sumsq_centered <= 0;
            fault_count <= 0;
        end else begin
            samples_meta <= requested_samples;
            samples_sync <= samples_meta;
            if (!active) begin
                sample_valid_reg <= 0;
                sample_last_reg <= 0;
                if (request_sync != done_toggle && samples_sync != 0 && samples_sync <= 16'd50000) begin
                    target_samples <= samples_sync;
                    sample_index <= 0;
                    sum_accumulator <= 0;
                    square_accumulator <= 0;
                    fault_accumulator <= 0;
                    sample_valid_reg <= 0;
                    sample_last_reg <= 0;
                    token <= request_sync;
                    active <= 1;
                end
            end else begin
                if (sample_valid_reg) begin
                    sum_accumulator <= sum_accumulator + sample_centered_reg;
                    square_accumulator <= square_accumulator + {16'd0, sample_square_reg};
                    if (sample_fault_reg) fault_accumulator <= fault_accumulator + 1'b1;
                    if (sample_last_reg) begin
                        active <= 0;
                        done_toggle <= token;
                        sum_centered <= sum_accumulator + sample_centered_reg;
                        sumsq_centered <= square_accumulator + {16'd0, sample_square_reg};
                        fault_count <= fault_accumulator + sample_fault_reg;
                    end
                end
                if (!sample_last_reg) begin
                    sample_centered_reg <= sample_centered;
                    sample_square_reg <= sample_product[31:0];
                    sample_fault_reg <= sample_fault;
                    sample_valid_reg <= 1;
                    if (sample_index == target_samples - 1'b1) begin
                        sample_last_reg <= 1;
                    end else begin
                        sample_index <= sample_index + 1'b1;
                    end
                end else begin
                    sample_valid_reg <= 0;
                end
            end
        end
    end
endmodule
