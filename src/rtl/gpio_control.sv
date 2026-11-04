`timescale 1ns/1ps
// Atomic per-bit arbitration: host wins only overlapping bits on the same cycle.
// A touch gesture acts once, on press; held/dragged fingers never repeat actions.
module gpio_control(
    input logic clk, rst_n,
    input logic host_valid,
    input logic [6:0] host_mask, host_value,
    input logic coord_valid, pen_up,
    input logic [10:0] coord_x, coord_y,
    output logic [6:0] state,
    output logic [31:0] sequence_number
);
    logic touch_held;
    logic [6:0] touch_mask, touch_value, next_state;
    integer row;
    always_comb begin
        touch_mask=0;touch_value=0;
        if(coord_valid && !pen_up && !touch_held) begin
            if(coord_y>=32 && coord_y<88) begin
                if(coord_x>=660 && coord_x<812) begin touch_mask=7'h7f;touch_value=0;end
                if(coord_x>=836 && coord_x<988) begin touch_mask=7'h7f;touch_value=7'h7f;end
            end
            for(integer i=0;i<7;i=i+1) begin
                if(coord_y>=132+i*52 && coord_y<176+i*52) begin
                    if(coord_x>=480 && coord_x<620) begin touch_mask[i]=1;touch_value[i]=0;end
                    if(coord_x>=650 && coord_x<790) begin touch_mask[i]=1;touch_value[i]=1;end
                end
            end
        end
        next_state=(state & ~touch_mask) | (touch_value & touch_mask);
        if(host_valid) next_state=(next_state & ~host_mask) | (host_value & host_mask);
    end
    always_ff @(posedge clk) begin
        if(!rst_n) begin state<=0;sequence_number<=0;touch_held<=0;end
        else begin
            if(pen_up) touch_held<=0;
            else if(coord_valid) touch_held<=1;
            state<=next_state;
            if(next_state!=state) sequence_number<=sequence_number+1;
        end
    end
endmodule
