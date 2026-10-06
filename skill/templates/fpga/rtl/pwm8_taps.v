// pwm8_taps - walks each channel's output delay line to its fine trim.
//
// The fine half of the skew calibration: a per-channel count of delay taps
// (ECP5 DELAYF, about 25 ps each, TAPS of them). The delay line has no
// "set to n" port, only LOADN (back to its reset value, 0 here), MOVE (one
// tap per rising edge) and DIRECTION (1 = less delay, 0 = more, as LiteX's
// ECP5DynamicDelay drives it), so this keeps the count each line is at and
// moves it one tap every 4 clocks until it equals the target. Targets load together on `load` (the core's commit
// landing). `moving` is high while any channel is still walking.
module pwm8_taps #(
    parameter CH = 8,
    parameter TB = 7            // bits of a tap count: TAPS = 2**TB
) (
    input                    clk,
    input                    rst,
    input                    load,
    input  [CH*TB-1:0]       target,    // channel k at [k*TB +: TB]
    output reg [CH-1:0]      loadn,
    output reg [CH-1:0]      move,
    output reg [CH-1:0]      direction,
    output                   moving
);
    reg [TB-1:0] cur [0:CH-1];
    reg [TB-1:0] tgt [0:CH-1];
    reg [1:0]    st  [0:CH-1];
    reg [CH-1:0] busy;
    assign moving = |busy;

    integer k;
    always @(posedge clk) begin
        for (k = 0; k < CH; k = k + 1) begin
            if (rst) begin
                loadn[k] <= 1'b0;           // the line back to DEL_VALUE = 0
                move[k] <= 1'b0;
                direction[k] <= 1'b0;
                cur[k] <= 0;
                tgt[k] <= 0;
                st[k] <= 0;
                busy[k] <= 1'b0;
            end else begin
                loadn[k] <= 1'b1;
                if (load)
                    tgt[k] <= target[k*TB +: TB];
                case (st[k])
                    // direction settles a clock before the MOVE edge
                    0: if (cur[k] != tgt[k] && !load) begin
                           direction[k] <= (tgt[k] < cur[k]);
                           busy[k] <= 1'b1;
                           st[k] <= 1;
                       end else begin
                           busy[k] <= load;
                       end
                    1: begin
                           move[k] <= 1'b1;
                           st[k] <= 2;
                       end
                    2: begin
                           move[k] <= 1'b0;
                           cur[k] <= direction[k] ? cur[k] - 1 : cur[k] + 1;
                           st[k] <= 3;
                       end
                    default: st[k] <= 0;
                endcase
            end
        end
    end
endmodule
