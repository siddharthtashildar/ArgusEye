module top (
    input  wire        clk,
    input  wire        rst,
    input  wire        uart_rx_pin,
    output wire [15:0] led,
    output wire [6:0]  seg,
    output wire [7:0]  an
);
    wire [7:0] rx_data;
    wire       rx_valid;

    uart_rx u_rx (
        .clk(clk), .rst(rst),
        .rx(uart_rx_pin),
        .data(rx_data),
        .valid(rx_valid)
    );

    reg        motion;
    reg [7:0]  strength;
    reg [26:0] blink_cnt;
    reg        blink;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            motion <= 0; strength <= 0;
            blink_cnt <= 0; blink <= 0;
        end else begin
            if (rx_valid) begin
                if      (rx_data == 8'h4D) motion   <= 1;
                else if (rx_data == 8'h43) motion   <= 0;
                else                       strength <= rx_data;
            end
            // blink at ~2Hz when motion
            blink_cnt <= blink_cnt + 1;
            if (blink_cnt == 27'd25_000_000) begin
                blink_cnt <= 0;
                blink     <= ~blink;
            end
        end
    end

    // LED bargraph — strength 0-100 across 15 LEDs
    // LED15 = motion blink
    genvar i;
    generate
        for (i = 0; i < 15; i = i + 1) begin
            assign led[i] = strength > (i * 7);
        end
    endgenerate
    assign led[15] = motion & blink;

    // 7-segment: show "HI" when motion, "----" when clear
    // an = active low digit select, seg = active low segments
    // show on all 8 digits
    assign an  = motion ? 8'b11111100 : 8'b00000000;

    // "H" = 7'b0001001, "I" = 7'b1111001
    // "-" = 7'b1011111
    assign seg = motion ? 7'b0001001 : 7'b1011111;

endmodule