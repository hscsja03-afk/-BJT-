`timescale 1ns/1ps
// RGB565 scanout: two line caches, one outstanding AXI read burst.
// The complete framebuffer lives in PS DDR. Base switches only at frame blanking.
module lcd_ddr_reader (
    (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF M_AXI, ASSOCIATED_RESET reset_n, FREQ_HZ 50000000" *)
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 clk CLK" *) input wire clk,
    (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 reset_n RST" *) input wire reset_n,
    input wire ui_write, input wire [31:0] ui_word,
    input wire [10:0] h_count, scan_x,
    input wire [9:0] v_count, scan_y,
    input wire scan_active, frame_start,
    output wire enabled, output wire [23:0] rgb,
    output wire [31:0] status, output reg [31:0] faults,
    (* X_INTERFACE_PARAMETER="PROTOCOL AXI4, ADDR_WIDTH 32, DATA_WIDTH 64, READ_WRITE_MODE READ_ONLY, NUM_READ_OUTSTANDING 1, MAX_BURST_LENGTH 16" *)
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARADDR" *) output wire [31:0] m_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARLEN" *) output wire [7:0] m_axi_arlen,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARSIZE" *) output wire [2:0] m_axi_arsize,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARBURST" *) output wire [1:0] m_axi_arburst,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARCACHE" *) output wire [3:0] m_axi_arcache,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARPROT" *) output wire [2:0] m_axi_arprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARVALID" *) output wire m_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARREADY" *) input wire m_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RDATA" *) input wire [63:0] m_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RRESP" *) input wire [1:0] m_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RLAST" *) input wire m_axi_rlast,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RVALID" *) input wire m_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RREADY" *) output wire m_axi_rready
);
    reg [29:0] pending_base, active_base;
    reg requested_enable, active_enable;
    reg [1:0] state;
    localparam IDLE=0, ADDRESS=1, DATA=2;
    reg [31:0] address;
    reg [9:0] loading_line;
    reg [7:0] word_index;
    reg [3:0] beat;
    reg failed;
    reg [1:0] valid;
    reg [9:0] tag0,tag1;
    (* ram_style="block" *) reg [63:0] lines[0:511];
    reg cache_write;
    reg [8:0] cache_address;
    reg [63:0] cache_data;
    reg [63:0] read_word;
    reg [1:0] pixel_lane;
    reg pixel_valid, line_ready;
    wire [15:0] pixel=read_word>>(pixel_lane*16);
    assign rgb=pixel_valid?{pixel[15:11],pixel[15:13],pixel[10:5],pixel[10:9],pixel[4:0],pixel[4:2]}:24'd0;
    assign enabled=active_enable;
    assign status={2'b0,active_base[29:6],4'b0,(state!=IDLE),active_enable};
    assign m_axi_araddr=address;
    assign m_axi_arlen=8'd15;
    assign m_axi_arsize=3'd3;
    assign m_axi_arburst=2'b01;
    assign m_axi_arcache=4'b0011;
    assign m_axi_arprot=0;
    assign m_axi_arvalid=state==ADDRESS;
    assign m_axi_rready=state==DATA;
    wire [9:0] visible_line=v_count-10'd23;
    wire cache_ready=visible_line[0] ? valid[1] && tag1==visible_line : valid[0] && tag0==visible_line;
    always @(posedge clk) begin
        // Isolate BRAM controls from the interconnect's asynchronously reset FIFO.
        cache_write<=reset_n && state==DATA && m_axi_rvalid;
        cache_address<={loading_line[0],word_index};
        cache_data<=m_axi_rdata;
        if(cache_write)lines[cache_address]<=cache_data;
        read_word<=lines[{scan_y[0],scan_x[9:2]}];
        pixel_lane<=scan_x[1:0];
        pixel_valid<=reset_n && active_enable && scan_active && line_ready;
        if(!reset_n) begin
            pending_base<=0;active_base<=0;requested_enable<=0;active_enable<=0;
            state<=IDLE;valid<=0;faults<=0;address<=0;loading_line<=0;
            word_index<=0;beat<=0;failed<=0;tag0<=0;tag1<=0;line_ready<=0;
        end else begin
            if(ui_write) begin
                // Page alignment also prevents any 128-byte burst crossing 4 KiB.
                if(ui_word[31:30]==2'b01 && ui_word[11:0]==0)
                    pending_base<=ui_word[29:0];
                if(ui_word[31:30]==2'b11 && ui_word[2])
                    requested_enable<=ui_word[0] && pending_base!=0;
            end
            // Lock validity before the first visible pixel; never reveal half a line.
            if(h_count==159) begin
                line_ready<=cache_ready;
                if(active_enable && v_count>=23 && v_count<623 && !cache_ready)
                    faults<=faults+1'b1;
            end
            if(frame_start && state==IDLE) begin
                active_base<=pending_base;active_enable<=requested_enable;
                valid<=0;
                if(requested_enable) begin
                    address<={2'b0,pending_base};loading_line<=0;
                    word_index<=0;beat<=0;failed<=0;state<=ADDRESS;
                end
            end else if(h_count==0 && v_count>=23 && v_count<622 && active_enable && state==IDLE) begin
                loading_line<=v_count-22;
                address<={2'b0,active_base}+((v_count-32'd22)<<11);
                valid[(v_count-22)&1]<=0;
                word_index<=0;beat<=0;failed<=0;state<=ADDRESS;
            end
            if(state==ADDRESS && m_axi_arready)state<=DATA;
            if(state==DATA && m_axi_rvalid) begin
                word_index<=word_index+1'b1;
                beat<=beat+1'b1;
                if(m_axi_rresp!=0 || m_axi_rlast!=(beat==15))failed<=1;
                if(m_axi_rlast) begin
                    if(beat!=15 || m_axi_rresp!=0 || failed) begin
                        state<=IDLE;faults<=faults+1'b1;
                    end else if(word_index==255) begin
                        state<=IDLE;valid[loading_line[0]]<=1;
                        if(loading_line[0])tag1<=loading_line;else tag0<=loading_line;
                    end else begin
                        state<=ADDRESS;address<=address+128;beat<=0;
                    end
                end
            end
        end
    end
endmodule
