`timescale 1ns/1ps
module tb_adc_statistics;
    reg bus_clk = 0;
    reg sample_clk = 0;
    reg reset_n = 0;
    reg request_toggle = 0;
    reg [15:0] requested_samples = 0;
    reg [15:0] data = 16'd32768;
    reg overrange = 0;
    wire done_toggle;
    wire signed [31:0] sum_centered;
    wire [47:0] sumsq_centered;
    wire [31:0] fault_count;
    integer timeout_cycles = 0;

    always #5 bus_clk = ~bus_clk;
    always #10 sample_clk = ~sample_clk;

    adc_statistics dut(
        .bus_clk(bus_clk), .sample_clk(sample_clk), .reset_n(reset_n),
        .request_toggle(request_toggle), .requested_samples(requested_samples),
        .data(data), .overrange(overrange), .done_toggle(done_toggle),
        .sum_centered(sum_centered), .sumsq_centered(sumsq_centered),
        .fault_count(fault_count)
    );

    always @(negedge sample_clk) begin
        if (reset_n && dut.active && !dut.sample_last_reg) begin
            case (dut.sample_index)
                0: data <= 16'd32768;
                1: data <= 16'd32769;
                2: data <= 16'd32766;
                3: data <= 16'hffff;
                default: data <= 16'd32768;
            endcase
        end
    end

    initial begin
        repeat (4) @(posedge sample_clk);
        reset_n = 1;
        requested_samples = 4;
        request_toggle = 1;
        while (done_toggle != 1 && timeout_cycles < 100) begin
            @(posedge sample_clk);
            timeout_cycles = timeout_cycles + 1;
        end
        #1;
        if (done_toggle != 1) $fatal(1, "statistics request timed out");
        if (sum_centered !== 32'sd32766) $fatal(1, "sum mismatch: %0d", sum_centered);
        if (sumsq_centered !== 48'd1073676294) $fatal(1, "sum of squares mismatch: %0d", sumsq_centered);
        if (fault_count !== 32'd1) $fatal(1, "fault count mismatch: %0d", fault_count);
        $display("ADC_STATISTICS_PASS sum=%0d sumsq=%0d faults=%0d", sum_centered,
                 sumsq_centered, fault_count);
        $finish;
    end
endmodule
