`timescale 1ns / 1ps

// Source-synchronous LCD output register. Signals launch on DCLK's rising
// edge and remain stable across the EK79001's default falling sampling edge.
module lcd_output_stage (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        video_enable,
    input  logic        pixel_active,
    input  logic [23:0] pixel_rgb,
    output logic        lcd_de,
    output logic [23:0] lcd_rgb_data,
    output logic        lcd_rgb_oe
);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            lcd_rgb_data <= 24'd0;
            lcd_de       <= 1'b0;
        end else begin
            lcd_rgb_data <= pixel_rgb;
            lcd_de       <= pixel_active && video_enable;
        end
    end

    assign lcd_rgb_oe = lcd_de;

endmodule
