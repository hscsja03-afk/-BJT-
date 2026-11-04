`timescale 1ns/1ps
// 1024x600、16色；保留旧512x300协议，控制字bit1选择原生模式。
module lcd_graphics(
    input logic clk, rst_n, write,
    input logic [31:0] word_data,
    input logic [10:0] x,
    input logic [9:0] y,
    input logic active,
    output logic enabled,
    output logic [23:0] rgb
);
    (* ram_style="block" *) logic [7:0] pixels[0:307199];
    logic [7:0] pair_value;
    logic odd_pixel, valid_pixel, native_mode;
    wire [18:0] address = active && x<1024 && y<600 ?
        (native_mode ? {y,9'b0}+{10'b0,x[9:1]} : {2'b0,y[9:1],8'b0}+{11'b0,x[9:2]}) : 19'd0;
    wire [18:0] write_address = word_data[29] ? word_data[18:0] : {2'b0,word_data[16:0]};
    wire [7:0] write_pair = word_data[29] ? word_data[26:19] : word_data[24:17];
    wire [3:0] ink = odd_pixel ? pair_value[7:4] : pair_value[3:0];
    always_ff @(posedge clk) begin
        if(!rst_n) begin enabled<=0;native_mode<=0;end
        else if(write && word_data[31:30]==2'b11) begin enabled<=word_data[0];native_mode<=word_data[1];end
        if(rst_n && write && word_data[31:30]==2'b10 &&
           (word_data[29] ? write_address<307200 : write_address<76800))
            pixels[write_address]<=write_pair;
        pair_value<=pixels[address];
        odd_pixel<=native_mode ? x[0] : x[1];
        valid_pixel<=rst_n && active && x<1024 && y<600;
    end
    always_comb begin
        case(ink)
            0:rgb=24'h0D1626; 1:rgb=24'h1C2A40;
            2:rgb=24'hE8F0FF; 3:rgb=24'h92A8C9;
            4:rgb=24'h2463C5; 5:rgb=24'h087F69;
            6:rgb=24'h41DBA3; 7:rgb=24'hFFBE55;
            8:rgb=24'hEF7373; 9:rgb=24'hB69CFF;
            10:rgb=24'h30445F; 11:rgb=24'hFFFFFF;
            12:rgb=24'h763A20; 13:rgb=24'hFFDBA8;
            14:rgb=24'h60C8FF; 15:rgb=24'h000000;
        endcase
        if(!valid_pixel) rgb=0;
    end
endmodule
