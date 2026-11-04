`timescale 1ns/1ps
module tb_lcd_ddr;
    reg clk=0;always #10 clk=~clk;
    reg reset_n=0,ui_write=0;reg [31:0] ui_word=0;
    wire [10:0] h,x;wire [9:0] v,y;wire active,frame;
    wire enabled;wire [23:0] rgb;wire [31:0] status,faults;
    wire [31:0] araddr;wire [7:0] arlen;wire [2:0] arsize,arprot;
    wire [1:0] arburst;wire [3:0] arcache;wire arvalid,rready;
    reg arready=0,rvalid=0,rlast=0;reg [63:0] rdata=0;reg [1:0] rresp=0;
    lcd_timing timing(clk,reset_n,h,v,active,x,y,frame);
    wire [23:0] text_rgb;
    dac_text text_plane(.clk(clk),.rst_n(reset_n),.write(ui_write),.word_data(ui_word),
                       .x(x),.y(y),.active(active),.rgb(text_rgb));
    lcd_ddr_reader dut(clk,reset_n,ui_write,ui_word,h,x,v,y,active,frame,
        enabled,rgb,status,faults,araddr,arlen,arsize,arburst,arcache,arprot,arvalid,arready,rdata,rresp,rlast,rvalid,rready);
    function [15:0] pattern(input [31:0] address);
        pattern=(address>>1)^((address>>20)*16'hf800);
    endfunction
    function [23:0] expand(input [15:0] p);
        expand={p[15:11],p[15:13],p[10:5],p[10:9],p[4:0],p[4:2]};
    endfunction
    integer ticks=0,read_beat=-1,checked=0,bursts=0;
    reg [31:0] read_address;
    reg [23:0] expected;reg compare=0;
    reg inject_error=0;
    // Vary address and data backpressure; hold valid data until accepted.
    always @(posedge clk) begin
        ticks<=ticks+1;arready<=ticks%7==0;
        if(arvalid && arready) begin
            if(read_beat!=-1 || arlen!=15 || arsize!=3 || arburst!=1 || araddr[11:0]>3968)
                $fatal(1,"AXI contract violation");
            read_address<=araddr;read_beat<=0;bursts<=bursts+1;
        end
        if(rvalid && rready) begin
            rvalid<=0;
            if(rlast)read_beat<=-1;else read_beat<=read_beat+1;
        end else if(!rvalid && read_beat>=0 && ticks%3!=0) begin
            for(integer lane=0;lane<4;lane=lane+1)
                rdata[lane*16+:16]<=pattern(read_address+read_beat*8+lane*2);
            rlast<=read_beat==15;rvalid<=1;
            rresp<=inject_error?2'b10:2'b00;
            if(inject_error)inject_error<=0;
        end
        if(reset_n && enabled && active && compare) begin
            expected=expand(pattern((status & 32'h3fffffc0)+y*2048+x*2));
            #1;if(rgb!==expected)$fatal(1,"Pixel mismatch x=%d y=%d actual=%h expected=%h",x,y,rgb,expected);
            checked=checked+1;
        end
    end
    task command(input [31:0] word);
        @(negedge clk);ui_word=word;ui_write=1;
        @(negedge clk);ui_write=0;
    endtask
    initial begin
        repeat(4)@(negedge clk);reset_n=1;
        command(32'h40100000);command(32'hc0000005);
        wait(enabled);compare=1;
        wait(v==300 && h==0);
        command(32'h40200000);
        if((status&32'h3fffffc0)!=32'h00100000)$fatal(1,"Swap occurred outside blanking");
        wait((status&32'h3fffffc0)==32'h00200000);
        wait(v==624);
        if(checked<900000 || faults!=0)$fatal(1,"Coverage or underflow failure %d %d",checked,faults);
        command(32'hc0000004);
        wait(status[1:0]==0);
        repeat(100)@(negedge clk);
        if(arvalid || rready)$fatal(1,"DMA did not stop");
        compare=0;inject_error=1;
        command(32'hc0000005);
        wait(enabled);
        wait(v==23 && h==200);#1;
        if(faults==0 || rgb!=0)$fatal(1,"Failed AXI line was exposed");
        wait(v==24 && h==200);#1;
        if(rgb==0)$fatal(1,"Reader failed to recover on next line");
        command(32'hc0000004);wait(status[1:0]==0);
        if(text_plane.cells[0]!==12'h020)$fatal(1,"DDR address corrupted text plane");
        command(32'h0123000c);@(negedge clk);
        if(text_plane.cells[12]!==12'h123)$fatal(1,"Legacy text write was lost");
        $display("PASS LCD DDR pixels=%d bursts=%d",checked,bursts);$finish;
    end
    initial begin #100000000;$fatal(1,"Timeout");end
endmodule
