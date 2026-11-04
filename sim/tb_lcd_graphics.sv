`timescale 1ns/1ps
module tb_lcd_graphics;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,write=0,active=1;
    reg [31:0] word_data=0;
    reg [10:0] x=0;
    reg [9:0] y=0;
    wire enabled;
    wire [23:0] rgb;
    lcd_graphics dut(.*);
    task put(input [31:0] value);
        @(negedge clk);write=1;word_data=value;
        @(negedge clk);write=0;
    endtask
    task pixel(input integer xx, yy, input [23:0] expected);
        @(negedge clk);x=xx;y=yy;
        @(posedge clk);#1;
        if(rgb!==expected) $fatal(1,"Pixel %d,%d: %h != %h",xx,yy,rgb,expected);
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        if(enabled!==0) $fatal(1,"Reset did not disable graphics");
        put(32'h80000000 | (32'h76<<17));
        put(32'h80000000 | 76799 | (32'he9<<17));
        put(32'hc0000001);
        if(!enabled) $fatal(1,"Enable failed");
        pixel(0,0,24'h41DBA3);pixel(1,1,24'h41DBA3);
        pixel(2,0,24'hFFBE55);pixel(3,1,24'hFFBE55);
        pixel(1020,598,24'hB69CFF);pixel(1023,599,24'h60C8FF);
        put(32'h00200000); // 字符写入不能改变图层。
        pixel(0,0,24'h41DBA3);
        active=0;pixel(0,0,0);active=1;
        put(32'hc0000000);
        if(enabled) $fatal(1,"Disable failed");
        // 原生像素相邻不复制；覆盖行边界和最高地址。
        put(32'ha0000000 | (32'h76<<19));
        put(32'ha0000000 | 511 | (32'h23<<19));
        put(32'ha0000000 | 512 | (32'h45<<19));
        put(32'ha0000000 | 307199 | (32'he9<<19));
        put(32'hc0000003);
        pixel(0,0,24'h41DBA3);pixel(1,0,24'hFFBE55);
        pixel(1022,0,24'h92A8C9);pixel(1023,0,24'hE8F0FF);
        pixel(0,1,24'h087F69);pixel(1,1,24'h2463C5);
        pixel(1022,599,24'hB69CFF);pixel(1023,599,24'h60C8FF);
        put(32'ha0000000 | 307200 | (32'hff<<19)); // 越界写不得回卷。
        pixel(0,0,24'h41DBA3);
        pixel(1024,0,0);pixel(0,600,0);
        put(32'hc0000001); // 老客户端仍可返回2倍显示。
        pixel(0,0,24'h41DBA3);pixel(1,1,24'h41DBA3);
        rst_n=0;@(posedge clk);#1;
        if(enabled || dut.native_mode) $fatal(1,"Reset failed");
        $display("PASS LCD GRAPHICS");$finish;
    end
endmodule
