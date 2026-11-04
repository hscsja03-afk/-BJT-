`timescale 1ns/1ps
module lcd_gpio_top(
    input sys_clk, sys_rst_n,
    output reg [31:0] ui_event,
    input ui_ack,ui_write,
    input [1:0] ui_page,
    input [31:0] ui_word,
`ifdef ADDA_LCD_DDR
    input ddr_enabled,
    input [23:0] ddr_rgb,
    output [10:0] ddr_h_count,ddr_scan_x,
    output [9:0] ddr_v_count,ddr_scan_y,
    output ddr_active,ddr_frame_start,
`endif
    output lcd_de,lcd_hs,lcd_vs,lcd_bl,lcd_clk,lcd_rst_n,
    inout [23:0] lcd_rgb,
    output touch_scl,touch_rst_n,
    inout touch_sda,touch_int,
    input gpio_cmd_valid,
    input [6:0] gpio_cmd_mask,gpio_cmd_value,
    output [6:0] gpio_state,gpio_sense,
    output [31:0] gpio_sequence,
    inout [6:0] ext_gpio
);
    wire [10:0] scan_x,coord_x,coord_y;
    wire [9:0] scan_y;
    wire scan_active,frame_start,coord_valid,pen_up;
    wire [32:0] event_data;
    wire event_toggle;
    wire [23:0] pixel_rgb,rgb_data,gpio_rgb,text_rgb;
    reg touch_held,text_select;
    wire graphics_enabled;
    wire [23:0] graphics_rgb;
    assign pixel_rgb=graphics_enabled?graphics_rgb:(text_select?text_rgb:gpio_rgb);
`ifdef ADDA_LCD_DDR
    assign graphics_enabled=ddr_enabled;
    assign graphics_rgb=ddr_rgb;
    assign ddr_scan_x=scan_x;assign ddr_scan_y=scan_y;
    assign ddr_active=scan_active;assign ddr_frame_start=frame_start;
`else
    lcd_graphics u_graphics(.clk(sys_clk),.rst_n(sys_rst_n),.write(ui_write),.word_data(ui_word),
        .x(scan_x),.y(scan_y),.active(scan_active),.enabled(graphics_enabled),.rgb(graphics_rgb));
`endif
    always @(posedge sys_clk) begin
        if(!sys_rst_n) begin ui_event<=0;touch_held<=0;text_select<=0;end
        else begin
            text_select<=ui_page!=0 || scan_y>=528;
            if(ui_ack) ui_event<=0;
            if(pen_up) touch_held<=0;
            if(coord_valid && !touch_held && !pen_up) begin
                touch_held<=1;
                if(!ui_event[31] && (graphics_enabled || ui_page!=0 || coord_y>=528))
                    ui_event<={1'b1,9'd0,coord_y,coord_x};
            end
        end
    end
    dac_text u_text(.clk(sys_clk),.rst_n(sys_rst_n),.write(ui_write),.word_data(ui_word),
        .x(scan_x),.y(scan_y),.active(scan_active),.rgb(text_rgb));
    wire rgb_oe;
    reg active_pipe,video_pipe;
    reg [19:0] power_count;
    wire video_enable=(power_count>=20'd1000000);
    wire [6:0] sense_raw;
    (* ASYNC_REG="TRUE" *) reg [6:0] sense_meta,sense_sync;
    assign gpio_sense=sense_sync;
    for(genvar i=0;i<7;i=i+1) begin:gpio_buffers
        IOBUF buffer(.I(gpio_state[i]),.T(1'b0),.O(sense_raw[i]),.IO(ext_gpio[i]));
    end
    always @(posedge sys_clk) begin
        if(!sys_rst_n) begin
            power_count<=0;active_pipe<=0;video_pipe<=0;sense_meta<=0;sense_sync<=0;
        end else begin
            if(power_count<20'd1000000) power_count<=power_count+1'b1;
            active_pipe<=scan_active;video_pipe<=video_enable;
            sense_meta<=sense_raw;sense_sync<=sense_meta;
        end
    end
    assign lcd_clk=sys_clk;
    assign lcd_hs=1'b1;assign lcd_vs=1'b1;
    assign lcd_rst_n=sys_rst_n && (power_count>=20'd50000);
    assign lcd_bl=video_enable;
    assign lcd_rgb=rgb_oe?rgb_data:24'hzzzzzz;
    lcd_timing u_timing(.clk(sys_clk),.rst_n(sys_rst_n),
`ifdef ADDA_LCD_DDR
        .h_count(ddr_h_count),.v_count(ddr_v_count),
`else
        .h_count(),.v_count(),
`endif
        .scan_active(scan_active),.scan_x(scan_x),.scan_y(scan_y),.frame_start(frame_start));
    gpio_ui u_ui(.clk(sys_clk),.scan_x(scan_x),.scan_y(scan_y),.scan_active(scan_active),
        .state(gpio_state),.sense(gpio_sense),.pixel_rgb(gpio_rgb));
    lcd_output_stage u_output(.clk(sys_clk),.rst_n(sys_rst_n),.video_enable(video_pipe),
        .pixel_active(active_pipe),.pixel_rgb(pixel_rgb),.lcd_de(lcd_de),
        .lcd_rgb_data(rgb_data),.lcd_rgb_oe(rgb_oe));
    gpio_control u_control(.clk(sys_clk),.rst_n(sys_rst_n),.host_valid(gpio_cmd_valid),
        .host_mask(gpio_cmd_mask),.host_value(gpio_cmd_value),.coord_valid(coord_valid && !touch_held && !graphics_enabled && ui_page==0 && coord_y<528),
        .pen_up(pen_up),.coord_x(coord_x),.coord_y(coord_y),.state(gpio_state),.sequence_number(gpio_sequence));
    touch_top u_touch_top(.clk(sys_clk),.rst_n(sys_rst_n),.lcd_id(16'h7016),.data(),
        .event_data(event_data),.event_toggle(event_toggle),.touch_scl(touch_scl),
        .touch_sda(touch_sda),.touch_int(touch_int),.touch_rst_n(touch_rst_n));
    touch_cdc u_touch_cdc(.clk(sys_clk),.rst_n(sys_rst_n),.event_data_async(event_data),
        .event_toggle_async(event_toggle),.coord_valid(coord_valid),.pen_up(pen_up),.coord_x(coord_x),.coord_y(coord_y));
endmodule
