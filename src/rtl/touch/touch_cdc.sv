`timescale 1ns / 1ps

// Multi-cycle-data CDC: event_data remains stable until the next toggle.
// The toggle and data bus pass through two stages before the event is emitted.
module touch_cdc (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [32:0] event_data_async,
    input  logic        event_toggle_async,
    output logic        coord_valid,
    output logic        pen_up,
    output logic [10:0] coord_x,
    output logic [10:0] coord_y
);

    (* ASYNC_REG = "TRUE" *) logic toggle_meta, toggle_sync;
    logic toggle_seen;
    logic [32:0] data_meta, data_sync;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            toggle_meta <= 1'b0;
            toggle_sync <= 1'b0;
            toggle_seen <= 1'b0;
            data_meta   <= 33'd0;
            data_sync   <= 33'd0;
            coord_valid <= 1'b0;
            pen_up      <= 1'b0;
            coord_x     <= 11'd0;
            coord_y     <= 11'd0;
        end else begin
            toggle_meta <= event_toggle_async;
            toggle_sync <= toggle_meta;
            data_meta   <= event_data_async;
            data_sync   <= data_meta;
            coord_valid <= 1'b0;
            pen_up      <= 1'b0;

            if (toggle_sync != toggle_seen) begin
                toggle_seen <= toggle_sync;
                coord_x <= data_sync[26:16];
                coord_y <= data_sync[10:0];
                if (data_sync[32])
                    coord_valid <= 1'b1;
                else
                    pen_up <= 1'b1;
            end
        end
    end

endmodule
