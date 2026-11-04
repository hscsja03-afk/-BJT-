`timescale 1ns/1ps
// The 2-bit background ROM contains Chinese text and hit-box outlines. Dynamic
// highlights use the same output register and synchronized pad sense as the PC.
module gpio_ui(
    input logic clk,
    input logic [10:0] scan_x,
    input logic [9:0] scan_y,
    input logic scan_active,
    input logic [6:0] state, sense,
    output logic [23:0] pixel_rgb
);
    (* rom_style="block" *) logic [1:0] background [0:614399];
    logic [1:0] ink;
    logic [10:0] x;
    logic [9:0] y;
    logic [19:0] address;
    logic [23:0] fill;
    initial $readmemh("gpio_background.mem",background);
    assign address=scan_active ? {scan_y,10'b0}+scan_x : 20'd0;
    always_ff @(posedge clk) begin
        ink<=background[address];x<=scan_x;y<=scan_y;
    end
    always_comb begin
        fill=24'h1C2A40;
        if(y>=32 && y<88) begin
            if(x>=660 && x<812) fill=(state==0)?24'h2463C5:24'h243752;
            if(x>=836 && x<988) fill=(state==7'h7f)?24'h087F69:24'h243752;
        end
        for(integer i=0;i<7;i=i+1) begin
            if(y>=132+i*52 && y<176+i*52) begin
                if(x>=480 && x<620) fill=!state[i]?24'h2463C5:24'h243752;
                if(x>=650 && x<790) fill=state[i]?24'h087F69:24'h243752;
                if(x>=834 && x<974) fill=(sense[i]!=state[i])?24'hB45322:(sense[i]?24'h087F69:24'h35465F);
            end
        end
        case(ink)
            0:pixel_rgb=24'h0D1626;
            1:pixel_rgb=fill;
            2:pixel_rgb=24'hEFF5FF;
            3:pixel_rgb=24'h91A6C3;
        endcase
        // Pad feedback: only the digit matching the actual sampled pad is lit.
        for(integer i=0;i<7;i=i+1) begin
            if(y>=140+i*52 && y<168+i*52 && ink==2) begin
                if(x>=850 && x<880 && sense[i]) pixel_rgb=24'h476274;
                if(x>=928 && x<958 && !sense[i]) pixel_rgb=24'h476274;
            end
        end
    end
endmodule
