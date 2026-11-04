`timescale 1ns/1ps
// Existing PS/ADDA block design plus a 50 MHz PL display. No new PS registers.
module adda_dac_gui_top (
    inout [53:0] FIXED_IO_mio,
    inout FIXED_IO_ps_clk, FIXED_IO_ps_porb, FIXED_IO_ps_srstb,
    input [15:0] adc_a, adc_b,
    input adc_dco_a, adc_dco_b, adc_or_a, adc_or_b,
    input clkgen_ld, clkgen_refmon, clkgen_status,
    output clkgen_reset_n, clkgen_sync_n,
    output [15:0] dac_a, dac_b,
    input dac_dco,
    inout tx1_scl, tx1_sda,
    output lcd_de, lcd_hs, lcd_vs, lcd_bl, lcd_clk, lcd_rst_n,
    inout [23:0] lcd_rgb,
    inout touch_scl, touch_sda, touch_int,
    output touch_rst_n,
    inout [6:0] ext_gpio
);
    wire lcd_bus_clk, lcd_bus_reset_n, touch_scl_drive;
    wire gpio_cmd_valid;
    wire [6:0] gpio_cmd_mask,gpio_cmd_value,gpio_state,gpio_sense;
    wire [31:0] gpio_sequence;
    wire [31:0] ui_event,ui_word;
    wire ui_ack,ui_write;
    wire [1:0] ui_page;
`ifdef ADDA_LCD_DDR
    wire ddr_enabled,ddr_active,ddr_frame_start;
    wire [23:0] ddr_rgb;
    wire [10:0] ddr_h_count,ddr_scan_x;
    wire [9:0] ddr_v_count,ddr_scan_y;
`endif
    system system_i (
`ifdef ADDA_LCD_DDR
        .ddr_enabled(ddr_enabled),.ddr_rgb(ddr_rgb),.ddr_h_count(ddr_h_count),
        .ddr_v_count(ddr_v_count),.ddr_scan_x(ddr_scan_x),.ddr_scan_y(ddr_scan_y),
        .ddr_active(ddr_active),.ddr_frame_start(ddr_frame_start),
`endif
        .ui_event(ui_event),.ui_ack(ui_ack),.ui_page(ui_page),.ui_write(ui_write),.ui_word(ui_word),
        .FIXED_IO_mio(FIXED_IO_mio), .FIXED_IO_ps_clk(FIXED_IO_ps_clk),
        .FIXED_IO_ps_porb(FIXED_IO_ps_porb), .FIXED_IO_ps_srstb(FIXED_IO_ps_srstb),
        .adc_a(adc_a), .adc_b(adc_b), .adc_dco_a(adc_dco_a), .adc_dco_b(adc_dco_b),
        .adc_or_a(adc_or_a), .adc_or_b(adc_or_b), .clkgen_ld(clkgen_ld),
        .clkgen_refmon(clkgen_refmon), .clkgen_status(clkgen_status),
        .clkgen_reset_n(clkgen_reset_n), .clkgen_sync_n(clkgen_sync_n),
        .dac_a(dac_a), .dac_b(dac_b), .dac_dco(dac_dco),
        .tx1_scl(tx1_scl), .tx1_sda(tx1_sda),
        .gpio_cmd_valid(gpio_cmd_valid),.gpio_cmd_mask(gpio_cmd_mask),.gpio_cmd_value(gpio_cmd_value),
        .gpio_state(gpio_state),.gpio_sense(gpio_sense),.gpio_sequence(gpio_sequence),
        .lcd_bus_clk(lcd_bus_clk), .lcd_bus_reset_n(lcd_bus_reset_n)
    );
    // The module has external 4.7k I2C pull-ups. Only drive low or release.
    assign touch_scl = touch_scl_drive ? 1'bz : 1'b0;
    lcd_gpio_top u_lcd (
`ifdef ADDA_LCD_DDR
        .ddr_enabled(ddr_enabled),.ddr_rgb(ddr_rgb),.ddr_h_count(ddr_h_count),
        .ddr_v_count(ddr_v_count),.ddr_scan_x(ddr_scan_x),.ddr_scan_y(ddr_scan_y),
        .ddr_active(ddr_active),.ddr_frame_start(ddr_frame_start),
`endif
        .ui_event(ui_event),.ui_ack(ui_ack),.ui_page(ui_page),.ui_write(ui_write),.ui_word(ui_word),
        .gpio_cmd_valid(gpio_cmd_valid),.gpio_cmd_mask(gpio_cmd_mask),.gpio_cmd_value(gpio_cmd_value),
        .gpio_state(gpio_state),.gpio_sense(gpio_sense),.gpio_sequence(gpio_sequence),.ext_gpio(ext_gpio),
        .sys_clk(lcd_bus_clk), .sys_rst_n(lcd_bus_reset_n),
        .lcd_de(lcd_de), .lcd_hs(lcd_hs), .lcd_vs(lcd_vs), .lcd_bl(lcd_bl),
        .lcd_clk(lcd_clk), .lcd_rst_n(lcd_rst_n), .lcd_rgb(lcd_rgb),
        .touch_scl(touch_scl_drive), .touch_sda(touch_sda),
        .touch_int(touch_int), .touch_rst_n(touch_rst_n)
    );
endmodule
