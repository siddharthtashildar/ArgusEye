module uart_rx #(parameter CLKS_PER_BIT = 10416)
(
    input clk,
    input rx,
    output reg [7:0] data,
    output reg valid
);

reg [13:0] clk_count = 0;
reg [3:0] bit_index = 0;
reg [9:0] rx_shift = 0;
reg receiving = 0;

always @(posedge clk) begin
    valid <= 0;

    if (!receiving && rx == 0) begin
        receiving <= 1;
        clk_count <= CLKS_PER_BIT / 2;
        bit_index <= 0;
    end

    else if (receiving) begin
        if (clk_count < CLKS_PER_BIT - 1)
            clk_count <= clk_count + 1;
        else begin
            clk_count <= 0;
            rx_shift[bit_index] <= rx;
            bit_index <= bit_index + 1;

            if (bit_index == 9) begin
                receiving <= 0;
                data <= rx_shift[8:1];
                valid <= 1;
            end
        end
    end
end

endmodule