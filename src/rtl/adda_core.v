`timescale 1ns/1ps
module adda_core (
    (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET reset_n, FREQ_HZ 50000000" *)
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 bus_clk CLK" *) input bus_clk,
    (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 reset_n RST" *) input reset_n,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *) input [15:0] s_axi_awaddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input [2:0] s_axi_awprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input s_axi_awvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output s_axi_awready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input s_axi_wvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output s_axi_wready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output reg [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input s_axi_bready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input [15:0] s_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input s_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output s_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output reg [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input s_axi_rready,
    input adc_dco_a, adc_dco_b, dac_dco,
    input [15:0] adc_a, adc_b,
    input adc_or_a, adc_or_b,
    output [15:0] dac_a, dac_b,
    output clkgen_reset_n, clkgen_sync_n,
    input clkgen_ld, clkgen_status, clkgen_refmon,
    inout tx1_scl, tx1_sda
`ifdef ADDA_DAC_GUI
    ,input [31:0] ui_event,
    output reg ui_ack,ui_write,
    output reg [1:0] ui_page,
    output reg [31:0] ui_word
`ifdef ADDA_LCD_DDR
    ,input [31:0] lcd_status,lcd_faults
`endif
`endif
`ifdef ADDA_GPIO
    ,output reg gpio_cmd_valid,
    output reg [6:0] gpio_cmd_mask, gpio_cmd_value,
    input [6:0] gpio_state, gpio_sense,
    input [31:0] gpio_sequence
`endif
);
    wire rst_a_n, rst_b_n, rst_d_n,dac_sample_clk,dac_locked;
`ifdef ADDA_DAC_GUI
    reg [1:0] awg_request;
    wire [1:0] awg_ack,awg_ack_sync;
    reg [31:0] awg_step_a,awg_step_b,awg_phase_a,awg_phase_b;
    reg awg_write_a,awg_write_b;
    reg [7:0] awg_address;
    reg [15:0] awg_data;
    wire [1:0] awg_busy=awg_request^awg_ack_sync;
    cdc_sync #(.WIDTH(2)) awg_ac(bus_clk,reset_n,awg_ack,awg_ack_sync);
    dac_awg awg(bus_clk,dac_sample_clk,rst_d_n,awg_request,
        awg_step_a,awg_step_b,awg_phase_a,awg_phase_b,
        awg_write_a,awg_write_b,~awg_request[0],~awg_request[1],
        awg_address,awg_data,awg_ack,dac_a,dac_b);
`endif
    wire adc_sample_a,adc_sample_b,adc_locked_a,adc_locked_b;
    wire [1:0] adc_locked_sync;
    adc_clocking aca(adc_dco_a,reset_n && control[0],adc_sample_a,adc_locked_a);
    adc_clocking acb(adc_dco_b,reset_n && control[0],adc_sample_b,adc_locked_b);
    cdc_sync #(.WIDTH(2)) adc_locks(bus_clk,reset_n,{adc_locked_b,adc_locked_a},adc_locked_sync);
    reset_sync ra(adc_sample_a,adc_locked_a,rst_a_n);
    reset_sync rb(adc_sample_b,adc_locked_b,rst_b_n);
    dac_clocking dc(dac_dco,reset_n && !control[2],dac_sample_clk,dac_locked);
    // MMCM LOCKED is low during MMCM reset or loss of input clock. Synchronize
    // its release directly; combining it with PS reset here adds a reset LUT.
    wire rst_count_d_n;
    // Separate reset release for the falling-edge generator and rising-edge
    // counter. Each domain gets a full cycle for recovery/removal at high rate.
    reset_sync #(.FALLING(1)) rd(dac_sample_clk,dac_locked,rst_d_n);
    reset_sync rdc(dac_sample_clk,dac_locked,rst_count_d_n);
    reg [31:0] control, mode, codes, step_a, step_b;
`ifdef ADDA_TX1
    // I2C open-drain only: 1 releases the pin to the board's 4.7k pull-up.
    reg [1:0] tx1_release;
    wire [1:0] tx1_input,tx1_raw;
    // Explicit IOBUF prevents OOC module-reference synthesis from turning
    // inferred internal tri-states into push-pull logic before top-level IO.
    IOBUF tx1_scl_buffer(.I(1'b0),.T(tx1_release[0]),.O(tx1_raw[0]),.IO(tx1_scl));
    IOBUF tx1_sda_buffer(.I(1'b0),.T(tx1_release[1]),.O(tx1_raw[1]),.IO(tx1_sda));
    cdc_sync #(.WIDTH(2)) tx1_inputs(bus_clk,reset_n,tx1_raw,tx1_input);
`endif
    reg cap_request, dac_request, cap_issued;
    reg stats_request, stats_issued;
    reg [15:0] stats_samples;
    reg [15:0] capture_stride;
    reg [12:0] capture_count;
    wire cap_ack_a, cap_ack_b, dac_ack;
    wire stats_ack_a, stats_ack_b;
    wire [1:0] stats_ack_sync;
    wire [2:0] ack_sync, clock_status;
    wire dac_locked_sync;
    cdc_sync lock_sync(bus_clk,reset_n,dac_locked,dac_locked_sync);
    cdc_sync #(.WIDTH(3)) ac(bus_clk,reset_n,{dac_ack,cap_ack_b,cap_ack_a},ack_sync);
    cdc_sync #(.WIDTH(2)) stats_ac(bus_clk,reset_n,{stats_ack_b,stats_ack_a},stats_ack_sync);
    cdc_sync #(.WIDTH(3)) cs(bus_clk,reset_n,{clkgen_refmon,clkgen_status,clkgen_ld},clock_status);
    wire cap_busy=(ack_sync[0]!=cap_request)||(ack_sync[1]!=cap_request);
    wire dac_busy=(ack_sync[2]!=dac_request);
    wire cap_done_a=cap_issued && (ack_sync[0]==cap_request);
    wire cap_done_b=cap_issued && (ack_sync[1]==cap_request);
    wire stats_busy=(stats_ack_sync[0]!=stats_request)||(stats_ack_sync[1]!=stats_request);
    wire stats_complete=stats_issued && !stats_busy;
    assign clkgen_reset_n=reset_n && control[0];
    assign clkgen_sync_n=control[1];
    wire [31:0] count_a,count_b,count_d;
    clock_counter ca(adc_sample_a,rst_a_n,bus_clk,reset_n,count_a);
    clock_counter cb(adc_sample_b,rst_b_n,bus_clk,reset_n,count_b);
    clock_counter cd(dac_sample_clk,rst_count_d_n,bus_clk,reset_n,count_d);
    reg [15:0] read_addr;
    wire [16:0] mem_a,mem_b;
    wire [11:0] capture_address = (read_addr[15:12]==1 || read_addr[15:12]==2) ? {2'b0,read_addr[11:2]} : read_addr[13:2];
    // One shared input stage isolates external timing from RAM and arithmetic.
    // Data and OR use the same edge/latency; no cross-channel alignment claim.
    (* IOB="TRUE" *) reg [16:0] adc_input_a,adc_input_b;
    always @(posedge adc_sample_a) adc_input_a <= {adc_or_a,adc_a};
    always @(posedge adc_sample_b) adc_input_b <= {adc_or_b,adc_b};
    adc_capture #(.ADDR_BITS(12)) capture_a(adc_sample_a,rst_a_n,cap_request,adc_input_a[15:0],adc_input_a[16],cap_ack_a,bus_clk,capture_address,mem_a,capture_stride,capture_count);
    adc_capture #(.ADDR_BITS(12)) capture_b(adc_sample_b,rst_b_n,cap_request,adc_input_b[15:0],adc_input_b[16],cap_ack_b,bus_clk,capture_address,mem_b,capture_stride,capture_count);
    wire signed [31:0] stats_sum_a,stats_sum_b;
    wire [47:0] stats_sumsq_a,stats_sumsq_b;
    wire [31:0] stats_faults_a,stats_faults_b;
    // Existing driver order is RX1=ADC B and RX2=ADC A.
    adc_statistics stats_a(bus_clk,adc_sample_a,rst_a_n,stats_request,stats_samples,
        adc_input_a[15:0],adc_input_a[16],stats_ack_a,stats_sum_a,stats_sumsq_a,stats_faults_a);
    adc_statistics stats_b(bus_clk,adc_sample_b,rst_b_n,stats_request,stats_samples,
        adc_input_b[15:0],adc_input_b[16],stats_ack_b,stats_sum_b,stats_sumsq_b,stats_faults_b);
`ifdef ADDA_DAC_GUI
    wire [15:0] unused_dac_a,unused_dac_b;
    dac_generator generator(dac_sample_clk,rst_d_n,dac_request,mode[1:0],codes,step_a,step_b,dac_ack,unused_dac_a,unused_dac_b);
`else
    dac_generator generator(dac_sample_clk,rst_d_n,dac_request,mode[1:0],codes,step_a,step_b,dac_ack,dac_a,dac_b);
`endif

    // AW and W are independent channels. Hold either until both have arrived.
    reg aw_full,w_full;
    reg [15:0] aw_address;
    reg [31:0] w_data;
    reg [3:0] w_strobe;
    assign s_axi_awready=!aw_full && !s_axi_bvalid;
    assign s_axi_wready=!w_full && !s_axi_bvalid;
    function [31:0] merge_bytes;
        input [31:0] old_value,new_value;
        input [3:0] strobe;
        integer i;
        begin
            merge_bytes=old_value;
            for(i=0;i<4;i=i+1) if(strobe[i]) merge_bytes[8*i+:8]=new_value[8*i+:8];
        end
    endfunction
    always @(posedge bus_clk) begin
        if (!reset_n) begin
            aw_full<=0;w_full<=0;aw_address<=0;w_data<=0;w_strobe<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;
            control<=6;mode<=0;codes<=32'h80008000;step_a<=0;step_b<=0;
            cap_request<=0;dac_request<=0;cap_issued<=0;
            stats_request<=0;stats_issued<=0;stats_samples<=0;
            capture_stride<=1;capture_count<=1024;
`ifdef ADDA_DAC_GUI
            awg_request<=0;awg_step_a<=0;awg_step_b<=0;awg_phase_a<=0;awg_phase_b<=0;
            awg_write_a<=0;awg_write_b<=0;awg_address<=0;awg_data<=0;
            ui_ack<=0;ui_write<=0;ui_page<=0;ui_word<=0;
`endif
`ifdef ADDA_GPIO
            gpio_cmd_valid<=0;gpio_cmd_mask<=0;gpio_cmd_value<=0;
`endif
`ifdef ADDA_TX1
            tx1_release<=2'b11;
`endif
        end else begin
`ifdef ADDA_GPIO
            gpio_cmd_valid<=0;
`endif
`ifdef ADDA_DAC_GUI
            awg_write_a<=0;awg_write_b<=0;ui_ack<=0;ui_write<=0;
`endif
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if (s_axi_awvalid && s_axi_awready) begin aw_address<=s_axi_awaddr;aw_full<=1;end
            if (s_axi_wvalid && s_axi_wready) begin w_data<=s_axi_wdata;w_strobe<=s_axi_wstrb;w_full<=1;end
            if (aw_full && w_full && !s_axi_bvalid) begin
                aw_full<=0;w_full<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
                case(aw_address)
                    16'h00d0: begin
                        if(w_strobe!=4'hf || w_data<8 || w_data>4096 || cap_busy) s_axi_bresp<=2;
                        else capture_count<=w_data[12:0];
                    end
                    16'h00c8: begin
                        if(w_strobe!=4'hf || w_data<1 || w_data>256 || cap_busy) s_axi_bresp<=2;
                        else capture_stride<=w_data[15:0];
                    end
                    16'h0004: control<=merge_bytes(control,w_data,w_strobe);
                    16'h0008: begin
                        if(w_strobe[0]) begin
                            if ((w_data[0] && (cap_busy || stats_busy))||(w_data[1] && dac_busy)) s_axi_bresp<=2;
                            else begin
                                if(w_data[0]) begin cap_request<=~cap_request;cap_issued<=1;end
                                if(w_data[1]) dac_request<=~dac_request;
                            end
                        end
                    end
                    16'h0010: if(dac_busy) s_axi_bresp<=2;else mode<=merge_bytes(mode,w_data,w_strobe);
                    16'h0014: if(dac_busy) s_axi_bresp<=2;else codes<=merge_bytes(codes,w_data,w_strobe);
                    16'h0018: if(dac_busy) s_axi_bresp<=2;else step_a<=merge_bytes(step_a,w_data,w_strobe);
                    16'h001c: if(dac_busy) s_axi_bresp<=2;else step_b<=merge_bytes(step_b,w_data,w_strobe);
                    16'h009c: begin
                        if(w_strobe!=4'hf || w_data>50000 || w_data<8 || stats_busy) s_axi_bresp<=2;
                        else stats_samples<=w_data[15:0];
                    end
                    16'h00a0: begin
                        if(w_strobe!=4'hf || w_data!=1 || stats_samples<8 || stats_samples>50000 ||
                           stats_busy || cap_busy) s_axi_bresp<=2;
                        else begin stats_request<=~stats_request;stats_issued<=1;end
                    end
`ifdef ADDA_GPIO
                    16'h0050: begin
                        // One atomic masked command. Reject partial/malformed writes.
                        if(w_strobe!=4'hf || (w_data & 32'hffff8080)!=0) s_axi_bresp<=2;
                        else begin
                            gpio_cmd_mask<=w_data[14:8];gpio_cmd_value<=w_data[6:0];gpio_cmd_valid<=1;
                        end
                    end
`endif
`ifdef ADDA_TX1
                    16'h0040: if(w_strobe[0]) tx1_release<=w_data[1:0];
`endif
`ifdef ADDA_DAC_GUI
                    16'h0064: if(w_strobe==15 && w_data==1) ui_ack<=1;else s_axi_bresp<=2;
                    16'h0068: if(w_strobe==15 && w_data<4) ui_page<=w_data[1:0];else s_axi_bresp<=2;
                    16'h006c: if(w_strobe==15) begin ui_write<=1;ui_word<=w_data;end else s_axi_bresp<=2;
                    16'h0088: if(w_strobe!=15 || w_data>3 || (awg_busy&w_data[1:0])!=0 || !dac_locked_sync) s_axi_bresp<=2;
                        else awg_request<=awg_request^w_data[1:0];
                    16'h008c: if(w_strobe!=15 || awg_busy[0]) s_axi_bresp<=2;else awg_step_a<=w_data;
                    16'h0090: if(w_strobe!=15 || awg_busy[1]) s_axi_bresp<=2;else awg_step_b<=w_data;
                    16'h0094: if(w_strobe!=15 || awg_busy[0]) s_axi_bresp<=2;else awg_phase_a<=w_data;
                    16'h0098: if(w_strobe!=15 || awg_busy[1]) s_axi_bresp<=2;else awg_phase_b<=w_data;
                    default: begin
                        if(w_strobe!=15 || aw_address[1:0]!=0 || aw_address[11:10]!=0 || !dac_locked_sync) s_axi_bresp<=2;
                        else if(aw_address[15:12]==3 && !awg_busy[0]) begin awg_write_a<=1;awg_address<=aw_address[9:2];awg_data<=w_data[15:0];end
                        else if(aw_address[15:12]==4 && !awg_busy[1]) begin awg_write_b<=1;awg_address<=aw_address[9:2];awg_data<=w_data[15:0];end
                        else s_axi_bresp<=2;
                    end
`else
                    default:s_axi_bresp<=2;
`endif
                endcase
            end
        end
    end
    reg [1:0] read_wait;
    assign s_axi_arready=!s_axi_rvalid && read_wait==0;
    always @(posedge bus_clk) begin
        if (!reset_n) begin
            s_axi_rvalid<=0;s_axi_rdata<=0;s_axi_rresp<=0;read_wait<=0;read_addr<=0;
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if (s_axi_arvalid && s_axi_arready) begin read_addr<=s_axi_araddr;read_wait<=2;end
            else if(read_wait!=0) begin
                read_wait<=read_wait-1'b1;
                if(read_wait==1) begin
                    s_axi_rvalid<=1;s_axi_rresp<=0;s_axi_rdata<=0;
                    case(read_addr)
                        16'h00c4:s_axi_rdata<=32'h53435001;
                        16'h00c8:s_axi_rdata<={16'd0,capture_stride};
                        16'h00cc:s_axi_rdata<=32'd4096;
                        16'h00d0:s_axi_rdata<={19'd0,capture_count};
                        16'h00d8:s_axi_rdata<={30'd0,adc_locked_sync};
`ifdef ADDA_ADC_DIVIDER
                        16'h00d4:s_axi_rdata<=`ADDA_ADC_DIVIDER;
`else
                        16'h00d4:s_axi_rdata<=32'd20;
`endif
                        16'h0000:s_axi_rdata<=32'h41444441;
`ifdef ADDA_DAC_GUI
                        16'h0060:s_axi_rdata<=ui_event;
                        16'h0068:s_axi_rdata<={30'd0,ui_page};
                        16'h0080:s_axi_rdata<=32'h41574701;
                        16'h0084:s_axi_rdata<={22'd0,awg_ack_sync,6'd0,awg_busy};
`endif
                        16'h0004:s_axi_rdata<=control;
                        16'h0008:s_axi_rdata<=0;
                        // Bit31 advertises extended capture, safe to read on legacy RTL.
                        16'h000c:s_axi_rdata<={1'b1,
`ifdef ADDA_DAC_GUI
                            1'b1,
`else
                            1'b0,
`endif
                            2'b11,
`ifdef ADDA_DAC_GUI
                            1'b1, // Native 1024x600 graphics, status bit27.
`else
                            1'b0,
`endif
`ifdef ADDA_LCD_DDR
                            1'b1,15'b0,clock_status,3'b0,dac_locked_sync,cap_busy,dac_busy,cap_done_b,cap_done_a};
                        16'h00e0:s_axi_rdata<=lcd_status;
                        16'h00e4:s_axi_rdata<=lcd_faults;
`else
                            16'b0,clock_status,3'b0,dac_locked_sync,cap_busy,dac_busy,cap_done_b,cap_done_a};
`endif
                        16'h009c:s_axi_rdata<={16'd0,stats_samples};
                        16'h00a0:s_axi_rdata<={28'd0,stats_complete,stats_ack_sync,stats_busy};
                        // RX1 uses ADC B; RX2 uses ADC A, matching capture() ordering.
                        16'h00a4:s_axi_rdata<=stats_sum_b;
                        16'h00a8:s_axi_rdata<=stats_sumsq_b[31:0];
                        16'h00ac:s_axi_rdata<={16'd0,stats_sumsq_b[47:32]};
                        16'h00b0:s_axi_rdata<=stats_sum_a;
                        16'h00b4:s_axi_rdata<=stats_sumsq_a[31:0];
                        16'h00b8:s_axi_rdata<={16'd0,stats_sumsq_a[47:32]};
                        16'h00bc:s_axi_rdata<=stats_faults_b;
                        16'h00c0:s_axi_rdata<=stats_faults_a;
                        16'h0010:s_axi_rdata<=mode;
                        16'h0014:s_axi_rdata<=codes;
                        16'h0018:s_axi_rdata<=step_a;
                        16'h001c:s_axi_rdata<=step_b;
                        16'h0020:s_axi_rdata<=32'd1024;
                        16'h0024:s_axi_rdata<=count_a;
                        16'h0028:s_axi_rdata<=count_b;
                        16'h002c:s_axi_rdata<=count_d;
`ifdef ADDA_GPIO
                        16'h0048:s_axi_rdata<=32'h47504901;
                        16'h004c:s_axi_rdata<={17'd0,gpio_sense,1'b0,gpio_state};
                        16'h0050:s_axi_rdata<=0;
                        16'h0054:s_axi_rdata<=gpio_sequence;
`endif
`ifdef ADDA_TX1
                        16'h0040:s_axi_rdata<={22'b0,tx1_input,6'b0,tx1_release};
                        16'h0044:s_axi_rdata<=32'h54583101;
`endif
`ifdef ADDA_DAC_DIVIDER
                        16'h0030:s_axi_rdata<=32'd1000000000 / `ADDA_DAC_DIVIDER;
`elsif ADDA_DAC_100MSPS
                        16'h0030:s_axi_rdata<=32'd100000000;
`else
                        16'h0030:s_axi_rdata<=32'd50000000;
`endif
                        default:begin
                            if(read_addr[1:0]!=0) s_axi_rresp<=2;
                            else if(read_addr[15:12]==1 && cap_done_a) s_axi_rdata<={15'b0,mem_a};
                            else if(read_addr[15:12]==2 && cap_done_b) s_axi_rdata<={15'b0,mem_b};
                            else if(read_addr[15:14]==1 && cap_done_a && capture_address<capture_count) s_axi_rdata<={15'b0,mem_a};
                            else if(read_addr[15:14]==2 && cap_done_b && capture_address<capture_count) s_axi_rdata<={15'b0,mem_b};
                            else s_axi_rresp<=2;
                        end
                    endcase
                end
            end
        end
    end
endmodule
