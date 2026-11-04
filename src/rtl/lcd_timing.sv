`timescale 1ns / 1ps

// Fixed 1024x600 RGB timing for the ATK-MD0700R-1024600 in DE mode.
// The panel samples on DCLK's falling edge by default. All source data is
// therefore launched on sys_clk's rising edge and lcd_clk is sys_clk itself.
module lcd_timing #(
    parameter integer H_SYNC  = 20,
    parameter integer H_BACK  = 140,
    parameter integer H_DISP  = 1024,
    parameter integer H_FRONT = 160,
    parameter integer V_SYNC  = 3,
    parameter integer V_BACK  = 20,
    parameter integer V_DISP  = 600,
    parameter integer V_FRONT = 12
) (
    input  logic        clk,
    input  logic        rst_n,
    output logic [10:0] h_count,
    output logic [9:0]  v_count,
    output logic        scan_active,
    output logic [10:0] scan_x,
    output logic [9:0]  scan_y,
    output logic        frame_start
);

    localparam integer H_TOTAL = H_SYNC + H_BACK + H_DISP + H_FRONT;
    localparam integer V_TOTAL = V_SYNC + V_BACK + V_DISP + V_FRONT;
    localparam integer H_START = H_SYNC + H_BACK;
    localparam integer V_START = V_SYNC + V_BACK;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            h_count <= 11'd0;
            v_count <= 10'd0;
        end else if (h_count == H_TOTAL - 1) begin
            h_count <= 11'd0;
            if (v_count == V_TOTAL - 1)
                v_count <= 10'd0;
            else
                v_count <= v_count + 10'd1;
        end else begin
            h_count <= h_count + 11'd1;
        end
    end

    always_comb begin
        scan_active = (h_count >= H_START) && (h_count < H_START + H_DISP) &&
                      (v_count >= V_START) && (v_count < V_START + V_DISP);
        if (scan_active) begin
            scan_x = h_count - H_START;
            scan_y = v_count - V_START;
        end else begin
            scan_x = 11'd0;
            scan_y = 10'd0;
        end
        frame_start = (h_count == 0) && (v_count == 0);
    end

endmodule
