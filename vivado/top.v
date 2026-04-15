module top (
    input  wire        clk,
    input  wire        rst,
    input  wire        uart_rx_pin,
    output reg  [7:0]  an,
    output reg  [6:0]  seg
);

    wire [7:0] rx_data;
    wire       rx_valid;

    uart_rx u_rx (
        .clk(clk),
        .rst(rst),
        .rx(uart_rx_pin),
        .data(rx_data),
        .valid(rx_valid)
    );

    reg        motion;
    reg [7:0]  strength;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            motion   <= 0;
            strength <= 0;
        end else if (rx_valid) begin
            if      (rx_data == 8'h4D) motion <= 1; // 'M'
            else if (rx_data == 8'h43) motion <= 0; // 'C'
            else                       strength <= rx_data;
        end
    end

    reg [19:0] refresh_counter;
    wire [2:0] digit_select = refresh_counter[19:17];

    always @(posedge clk or posedge rst) begin
        if (rst)
            refresh_counter <= 0;
        else
            refresh_counter <= refresh_counter + 1;
    end

    reg [3:0] hex_to_decode;
    reg       is_char;

    always @(*) begin
        an = 8'b11111111;
        is_char = 0;
        hex_to_decode = 4'h0;

        case (digit_select)
            3'd7: begin
                an = 8'b01111111;
                is_char = 1;
            end
            3'd1: begin
                an = 8'b11111101;
                hex_to_decode = strength[7:4];
            end
            3'd0: begin
                an = 8'b11111110;
                hex_to_decode = strength[3:0];
            end
            default: an = 8'b11111111;
        endcase
    end

    always @(*) begin
        if (is_char) begin
            if (motion) seg = 7'b0001000; // 'A'
            else        seg = 7'b1001111; // 'I'
        end else begin
            case (hex_to_decode)
                4'h0: seg = 7'b0000001;
                4'h1: seg = 7'b1001111;
                4'h2: seg = 7'b0010010;
                4'h3: seg = 7'b0000110;
                4'h4: seg = 7'b1001100;
                4'h5: seg = 7'b0100100;
                4'h6: seg = 7'b0100000;
                4'h7: seg = 7'b0001111;
                4'h8: seg = 7'b0000000;
                4'h9: seg = 7'b0000100;
                4'hA: seg = 7'b0001000;
                4'hB: seg = 7'b1100000;
                4'hC: seg = 7'b0110001;
                4'hD: seg = 7'b1000010;
                4'hE: seg = 7'b0110000;
                4'hF: seg = 7'b0111000;
                default: seg = 7'b1111111;
            endcase
        end
    end
endmodule
