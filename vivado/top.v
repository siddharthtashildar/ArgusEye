module top(
    input clk,
    input rx,
    output [15:0] led,
    output [6:0] seg,
    output [3:0] an
);

wire [7:0] uart_data;
wire uart_valid;

uart_rx uart0 (
    .clk(clk),
    .rx(rx),
    .data(uart_data),
    .valid(uart_valid)
);

// ── Registers ─────────────────────
reg motion = 0;
reg [7:0] strength = 0;
reg [15:0] event_count = 0;
reg prev_motion = 0;

// ── UART decoding ─────────────────
always @(posedge clk) begin
    if (uart_valid) begin
        if (uart_data == "M")
            motion <= 1;
        else if (uart_data == "C")
            motion <= 0;
        else
            strength <= uart_data;
    end
end

// ── Event counter ─────────────────
always @(posedge clk) begin
    if (motion && !prev_motion)
        event_count <= event_count + 1;
    prev_motion <= motion;
end

// ── LED BAR (signal strength) ─────
assign led[7:0] = strength >> 5;

// ── Motion blinking LEDs ──────────
reg [25:0] blink = 0;
always @(posedge clk)
    blink <= blink + 1;

assign led[15:8] = motion ? {8{blink[25]}} : 0;

// ── 7-seg display ─────────────────
seven_seg seg0 (
    .clk(clk),
    .value(event_count),
    .seg(seg),
    .an(an)
);

endmodule