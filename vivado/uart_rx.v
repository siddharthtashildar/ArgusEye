module uart_rx (
    input  wire       clk,
    input  wire       rst,
    input  wire       rx,
    output reg  [7:0] data,
    output reg        valid
);

    localparam BAUD_DIV  = 14'd10416;
    localparam HALF_BAUD = 13'd5208;

    reg [13:0] baud_cnt;
    reg [3:0]  bit_cnt;
    reg [7:0]  shift_reg;
    reg        busy;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            baud_cnt  <= 0;
            bit_cnt   <= 0;
            shift_reg <= 0;
            busy      <= 0;
            data      <= 0;
            valid     <= 0;
        end else begin
            valid <= 0;
            if (!busy) begin
                if (rx == 0) begin
                    baud_cnt <= HALF_BAUD;
                    bit_cnt  <= 8;
                    busy     <= 1;
                end
            end else begin
                baud_cnt <= baud_cnt + 1;
                if (baud_cnt == BAUD_DIV) begin
                    baud_cnt <= 0;
                    if (bit_cnt > 0) begin
                        shift_reg <= {rx, shift_reg[7:1]};
                        bit_cnt   <= bit_cnt - 1;
                    end else begin
                        data  <= shift_reg;
                        valid <= 1;
                        busy  <= 0;
                    end
                end
            end
        end
    end
endmodule
