`timescale 1ns/1ps
module tb_dac_axi;
    reg bus_clk=0,aclk=0,bclk=0,dclk=0,drun=0,reset_n=0;
    wire gpio_cmd_valid;
    wire [6:0] gpio_cmd_mask,gpio_cmd_value,gpio_state;
    wire [31:0] gpio_sequence;
    gpio_control ctrl(.clk(bus_clk),.rst_n(reset_n),.host_valid(gpio_cmd_valid),.host_mask(gpio_cmd_mask),.host_value(gpio_cmd_value),
        .coord_valid(1'b0),.pen_up(1'b0),.coord_x(11'd0),.coord_y(11'd0),.state(gpio_state),.sequence_number(gpio_sequence));

    always #10 bus_clk=~bus_clk;
    real adc_half_period=8.0;
    always #(adc_half_period) aclk=~aclk;
    always #(adc_half_period) bclk=~bclk;
`ifdef ADDA_DAC_DIVIDER
    always #(`ADDA_DAC_DIVIDER/2.0) if(drun) dclk=~dclk;
`elsif ADDA_DAC_100MSPS
    always #5 if(drun) dclk=~dclk;
`else
    always #10 if(drun) dclk=~dclk;
`endif
    reg [15:0] a=0,b=100;
    always @(negedge aclk) a<=a+1;
    always @(negedge bclk) b<=b+1;
    wire [15:0] da,db;
    reg [15:0] awaddr=0,araddr=0;
    reg [31:0] wdata=0;
    reg [3:0] wstrb=15;
    reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    wire awready,wready,bvalid,arready,rvalid;
    wire [1:0] bresp,rresp;
    wire [31:0] rdata;
    wire cr,cs;
    tri1 tx1_scl,tx1_sda;
    reg tx1_external_low=0;
    assign tx1_sda=tx1_external_low?1'b0:1'bz;
    adda_core dut(.gpio_cmd_valid(gpio_cmd_valid),.gpio_cmd_mask(gpio_cmd_mask),.gpio_cmd_value(gpio_cmd_value),
        .ui_event(32'h80000001),.ui_ack(),.ui_write(),.ui_page(),.ui_word(),.gpio_state(gpio_state),.gpio_sense(gpio_state),.gpio_sequence(gpio_sequence),.bus_clk(bus_clk),.reset_n(reset_n),
        .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
        .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
        .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
        .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
        .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
        .adc_dco_a(aclk),.adc_dco_b(bclk),.dac_dco(dclk),.adc_a(a),.adc_b(b),
        .adc_or_a(a[4]),.adc_or_b(b[4]),.dac_a(da),.dac_b(db),
        .clkgen_reset_n(cr),.clkgen_sync_n(cs),.clkgen_ld(1'b1),.clkgen_status(1'b0),.clkgen_refmon(1'b1),
        .tx1_scl(tx1_scl),.tx1_sda(tx1_sda));
    task send_aw(input [15:0] address);
        begin
            @(negedge bus_clk);awaddr=address;awvalid=1;
            do @(posedge bus_clk);while(!awready);
            @(negedge bus_clk);awvalid=0;
        end
    endtask
    task send_w(input [31:0] value,input [3:0] strobe);
        begin
            @(negedge bus_clk);wdata=value;wstrb=strobe;wvalid=1;
            do @(posedge bus_clk);while(!wready);
            @(negedge bus_clk);wvalid=0;
        end
    endtask
    task write_reg(input [15:0] address,input [31:0] value,input [3:0] strobe,input integer order,input [1:0] expected);
        begin
            if(order==0) begin send_aw(address);repeat(3) @(negedge bus_clk);send_w(value,strobe);end
            else if(order==1) begin send_w(value,strobe);repeat(3) @(negedge bus_clk);send_aw(address);end
            else fork send_aw(address);send_w(value,strobe);join
            wait(bvalid);#1;
            if(bresp!==expected) $fatal(1,"BRESP %x at %x expected %x",bresp,address,expected);
            repeat(3) begin @(negedge bus_clk);if(!bvalid||bresp!==expected) $fatal(1,"Unstable B response");end
            bready=1;@(negedge bus_clk);bready=0;
        end
    endtask
    task read_reg(input [15:0] address,output [31:0] value,input [1:0] expected);
        begin
            @(negedge bus_clk);araddr=address;arvalid=1;
            do @(posedge bus_clk);while(!arready);
            @(negedge bus_clk);arvalid=0;
            wait(rvalid);#1;value=rdata;
            if(rresp!==expected) $fatal(1,"RRESP %x at %x expected %x",rresp,address,expected);
            repeat(2) begin @(negedge bus_clk);if(!rvalid||rdata!==value) $fatal(1,"Unstable R response");end
            rready=1;@(negedge bus_clk);rready=0;
        end
    endtask
    integer i,j,changes;
    reg [31:0] value,first_a,first_b,old;
    initial begin
        #200;@(negedge bus_clk);reset_n=1;
        repeat(20) @(negedge bus_clk);
        read_reg(0,value,0);if(value!==32'h41444441) $fatal(1,"ID");
`ifdef ADDA_TX1
        read_reg(16'h44,value,0);if(value!==32'h54583101) $fatal(1,"TX1 ID");
        read_reg(16'h40,value,0);if(value!==32'h303) $fatal(1,"I2C reset not released");
        write_reg(16'h40,1,1,0,0);
        if(tx1_scl!==1 || tx1_sda!==0) $fatal(1,"I2C SDA drive");
        write_reg(16'h40,2,2,1,0); // Other byte strobes must not alter pins.
        read_reg(16'h40,value,0);if(value!==32'h101) $fatal(1,"I2C WSTRB/input feedback");
        write_reg(16'h40,3,1,2,0);
        tx1_external_low=1;repeat(6) @(negedge bus_clk);
        if(tx1_sda!==0) $fatal(1,"I2C drives high against target ACK");
        read_reg(16'h40,value,0);if(value!==32'h103) $fatal(1,"I2C target ACK readback");
        tx1_external_low=0;repeat(6) @(negedge bus_clk);
        write_reg(16'h40,0,1,0,0);
        @(negedge bus_clk);reset_n=0;repeat(3) @(negedge bus_clk);
        if(tx1_scl!==1 || tx1_sda!==1) $fatal(1,"I2C reset must release both lines");
        reset_n=1;repeat(10) @(negedge bus_clk);
        $display("PASS: TX1 open-drain release, target ACK, synchronized input, byte strobes and reset");
`endif
        read_reg(16'h48,value,0);if(value!==32'h47504901) $fatal(1,"GPIO ID");
        read_reg(16'h4c,value,0);if(value!==0) $fatal(1,"GPIO reset state");
        for(integer g=0;g<7;g=g+1) begin
            write_reg(16'h50,((1<<g)<<8)|(1<<g),15,g%3,0);
            read_reg(16'h4c,value,0);if(value!==(((1<<(g+1))-1)*257)) $fatal(1,"GPIO masked write");
        end
        read_reg(16'h54,value,0);if(value!==7) $fatal(1,"GPIO sequence count");
        write_reg(16'h50,32'h7f00,1,0,2);
        write_reg(16'h50,32'h8000,15,1,2);
        write_reg(16'h50,32'h0080,15,2,2);
        read_reg(16'h4c,value,0);if(value!==32'h7f7f) $fatal(1,"Bad write changed GPIO");
        write_reg(16'h50,32'h7f00,15,0,0);
        read_reg(16'h4c,value,0);if(value!==0) $fatal(1,"GPIO clear all");
        $display("PASS GPIO AXI registers, masked writes, AW/W ordering, WSTRB/error rejection");
        read_reg(16'h30,value,0);
`ifdef ADDA_DAC_DIVIDER
        if(value!==(1000000000 / `ADDA_DAC_DIVIDER)) $fatal(1,"DAC profile identity");
`elsif ADDA_DAC_100MSPS
        if(value!==100000000) $fatal(1,"100 MSPS profile identity");
`else
        if(value!==50000000) $fatal(1,"50 MSPS profile identity");
`endif
        if(da!==16'h8000||db!==16'h8000||cr!==0||cs!==1) $fatal(1,"Reset defaults");
        read_reg(16'h1000,value,2); // No valid capture yet.
        write_reg(4,7,15,0,0);if(cr!==1) $fatal(1,"Clock reset");
        write_reg(16'h14,32'h12345678,15,1,0);
        write_reg(16'h14,32'hbbbbbbbb,4'b0101,2,0);
        read_reg(16'h14,value,0);if(value!==32'h12bb56bb) $fatal(1,"WSTRB");
        write_reg(16'h58,1,15,0,2);
        read_reg(16'h15,value,2);
        // DCO absent at startup: commit stays pending while MMCM is held in reset.
        write_reg(16'h10,1,15,0,0);write_reg(8,2,15,1,0);
        read_reg(12,value,0);if(!value[2]) $fatal(1,"Lost stopped-clock command");
        write_reg(16'h14,0,15,2,2);write_reg(8,2,15,0,2);
        drun=1;repeat(20) @(negedge bus_clk);write_reg(4,3,15,0,0);
        repeat(600) @(negedge bus_clk); // Real UNISIM MMCM acquisition, no mock clock.
        read_reg(12,value,0);if(value[2]) $fatal(1,"DAC ack timeout");
        if(!value[4]) $fatal(1,"MMCM did not lock");
        read_reg(16'hd4,value,0);if(value!==16) $fatal(1,"ADC timing profile");
        read_reg(16'hd8,value,0);if(value!==3) $fatal(1,"ADC MMCM did not lock at 62.5 MHz");
        
        read_reg(16'h80,value,0);if(value!==32'h41574701)$fatal(1,"AWG capability");
        read_reg(16'h60,value,0);if(value!==32'h80000001)$fatal(1,"LCD event");
        write_reg(16'h68,2,15,0,0);read_reg(16'h68,value,0);if(value!==2)$fatal(1,"LCD page");
        write_reg(16'h68,4,15,0,2);write_reg(16'h64,1,1,0,2);
        write_reg(16'h3000,999,1,0,2);write_reg(16'h3400,999,15,0,2);
        for(i=0;i<256;i=i+1) begin
            write_reg(16'h3000+i*4,16'h1234,15,i%3,0);
            write_reg(16'h4000+i*4,16'h5678,15,i%3,0);
        end
        if(da!==16'h8000 || db!==16'h8000)$fatal(1,"upload affected output");
        force dut.awg_ack_sync=0;
        write_reg(16'h88,3,15,0,0);
        write_reg(16'h3000,888,15,0,2);write_reg(16'h8c,1,15,0,2);
        write_reg(16'h88,1,15,0,2);
        release dut.awg_ack_sync;
        repeat(30) @(negedge bus_clk);
        if(da!==16'h1234 || db!==16'h5678)$fatal(1,"dual table commit");
        for(i=0;i<256;i=i+1)write_reg(16'h3000+i*4,16'h2222,15,i%3,0);
        if(da!==16'h1234 || db!==16'h5678)$fatal(1,"inactive bank leak");
        write_reg(16'h88,1,15,0,0);repeat(30)@(negedge bus_clk);
        if(da!==16'h2222 || db!==16'h5678)$fatal(1,"independent channel commit");
        $display("PASS AWG AXI bank isolation, independent commit, busy/partial/malformed guards, LCD registers");

        write_reg(8,1,15,2,0);
        write_reg(8,1,15,1,2); // Cannot overwrite an active snapshot.
        read_reg(16'h1000,value,2);
        for(i=0;i<400;i=i+1) begin read_reg(12,value,0);if(value[1:0]==3) break;end
        if(i==400) $fatal(1,"Capture timeout");
        read_reg(16'h1000,first_a,0);read_reg(16'h2000,first_b,0);
        for(i=0;i<1024;i=i+1) begin
            read_reg(16'h1000+4*i,value,0);
            if(value[15:0]!==((first_a+i)&65535)||value[16]!==value[4]) $fatal(1,"ADC A sample %d",i);
            read_reg(16'h2000+4*i,value,0);
            if(value[15:0]!==((first_b+i)&65535)||value[16]!==value[4]) $fatal(1,"ADC B sample %d",i);
        end
        read_reg(16'h1000,value,0);if(value!==first_a) $fatal(1,"Capture not frozen");
        write_reg(8,1,15,0,0);repeat(1500) @(negedge bus_clk);
        read_reg(16'h1000,value,0);if(value===first_a) $fatal(1,"Retrigger did not replace data");
        read_reg(16'h24,value,0);repeat(20) @(negedge bus_clk);read_reg(16'h24,old,0);
        if(old<=value) $fatal(1,"Clock monitor stalled");
        // The same bitstream must reacquire at the calibrated 50 MHz setting.
        write_reg(4,2,15,0,0);adc_half_period=10.0;
        repeat(20) @(negedge bus_clk);write_reg(4,3,15,0,0);
        repeat(600) @(negedge bus_clk);
        read_reg(16'hd8,value,0);if(value!==3) $fatal(1,"ADC MMCM did not relock at 50 MHz");
        write_reg(8,1,15,0,0);repeat(1500) @(negedge bus_clk);
        read_reg(16'h1000,first_a,0);
        for(i=0;i<1024;i=i+1) begin
            read_reg(16'h1000+4*i,value,0);
            if(value[15:0]!==((first_a+i)&65535)||value[16]!==value[4]) $fatal(1,"ADC 50 MHz sample %d",i);
        end
        $display("PASS ADC MMCM 62.5 and 50 MHz acquisition and sequential samples");
        // Runtime DCO loss is a fault requiring a complete PL/software restart.
        @(negedge dclk);drun=0;repeat(50) @(negedge bus_clk);
        read_reg(12,value,0);if(value[4]) $fatal(1,"Missing DAC clock fault");
        if(da!==16'h8000||db!==16'h8000) $fatal(1,"DAC did not return to midscale on unlock");
        $display("PASS: AXI AW/W ordering, response backpressure, WSTRB, CDC missing startup clock, ADC 2048 samples, retrigger, DAC sine, clock monitor, MMCM lock/loss");
        write_reg(16'h88,1,15,0,2);write_reg(16'h3000,1,15,0,2);
        $display("PASS DAC_GUI_AXI_SIMULATION");
        $finish;
    end
    initial begin #5000000;$fatal(1,"Global simulation timeout");end
endmodule
