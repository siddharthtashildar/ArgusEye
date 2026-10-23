module seven_seg(
    input clk,
    input [15:0] value,
    output reg [6:0] seg,
    output reg [3:0] an
);

reg [19:0] counter = 0;
reg [1:0] digit = 0;
reg [3:0] current;

always @(posedge clk)
    counter <= counter + 1;

always @(posedge clk)
    digit <= counter[19:18];

always @(*) begin
    case (digit)
        2'b00: begin an = 4'b1110; current = value % 10; end
        2'b01: begin an = 4'b1101; current = (value/10) % 10; end
        2'b10: begin an = 4'b1011; current = (value/100) % 10; end
        2'b11: begin an = 4'b0111; current = (value/1000) % 10; end
    endcase

    case (current)
        0: seg=7'b1000000; 1: seg=7'b1111001;
        2: seg=7'b0100100; 3: seg=7'b0110000;
        4: seg=7'b0011001; 5: seg=7'b0010010;
        6: seg=7'b0000010; 7: seg=7'b1111000;
        8: seg=7'b0000000; 9: seg=7'b0010000;
        default: seg=7'b1111111;
    endcase
end

endmodule