`timescale 1ns/1ps
// 64 x 37 cells, 16 x 16 font. One-cycle video latency.
module dac_text(
    input logic clk,rst_n,write,
    input logic [31:0] word_data,
    input logic [10:0] x,
    input logic [9:0] y,
    input logic active,
    output logic [23:0] rgb
);
    (* ram_style="distributed" *) logic [11:0] cells[0:4095];
    (* rom_style="distributed" *) logic [15:0] font[0:2047];
    logic [11:0] cell_value;
    logic [15:0] bits;
    logic [23:0] background,foreground;
    initial begin
        $readmemh("font.mem",font);
        for(integer i=0;i<4096;i=i+1) cells[i]=12'h020;
    end
    always_ff @(posedge clk) if(write && word_data[31:30]==2'b00) cells[word_data[11:0]]<=word_data[27:16];
    always_comb begin
        cell_value=cells[{y[9:4],x[9:4]}];
        bits=font[{cell_value[6:0],y[3:0]}];
        background=24'h0D1626;foreground=24'hE8F0FF;
        case(cell_value[11:8])
            1:begin background=24'h1C2A40;foreground=24'h92A8C9;end
            2:begin background=24'h2463C5;foreground=24'hFFFFFF;end
            3:begin background=24'h087F69;foreground=24'hFFFFFF;end
            4:begin background=24'h763A20;foreground=24'hFFDBA8;end
            default:begin end
        endcase
    end
    always_ff @(posedge clk) begin
        if(!rst_n || !active) rgb<=0;
        else rgb<=bits[15-x[3:0]]?foreground:background;
    end
endmodule
