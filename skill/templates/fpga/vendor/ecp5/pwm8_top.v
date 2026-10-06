// pwm8_top (ECP5) - the board top: clocks, pwm8_ctrl, one pwm8_serdes per
// channel. fpga_build.py sets the parameters from gateware.json (geometry,
// the PLL divides, CPB = sclk / baud) and the pins from its `board`.
module pwm8_top #(
    parameter CH = 8, N = 56, W = 4, PW = 6, CPB = 1648,
    parameter P1_CLKI = 1, P1_FB = 1, P1_OP = 45, P1_OS = 8,
    parameter P2_CLKI = 4, P2_FB = 1, P2_OP = 45, P2_OS = 2
) (
    input           clk_ref,
    input           uart_rx,
    output          uart_tx,
    output [CH-1:0] pwm
);
    wire eclk, sclk, gddr_rst, rst;
    pwm8_clocks #(.P1_CLKI(P1_CLKI), .P1_FB(P1_FB), .P1_OP(P1_OP), .P1_OS(P1_OS),
                  .P2_CLKI(P2_CLKI), .P2_FB(P2_FB), .P2_OP(P2_OP), .P2_OS(P2_OS)) clocks (
        .ref_clk(clk_ref), .eclk(eclk), .sclk(sclk), .gddr_rst(gddr_rst), .rst(rst));

    wire [CH*W-1:0] word;
    wire [CH-1:0]   loadn, move, dir;
    /* verilator lint_off PINCONNECTEMPTY */
    pwm8_ctrl #(.CH(CH), .N(N), .W(W), .PW(PW), .CPB(CPB)) ctrl (
        .clk(sclk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx), .word(word),
        .period_start(), .dly_loadn(loadn), .dly_move(move), .dly_dir(dir));
    /* verilator lint_on PINCONNECTEMPTY */

    genvar k;
    generate
        for (k = 0; k < CH; k = k + 1) begin : ch
            pwm8_serdes #(.W(W)) ser (.sclk(sclk), .eclk(eclk), .rst(gddr_rst),
                                      .d(word[k*W +: W]), .loadn(loadn[k]), .move(move[k]),
                                      .direction(dir[k]), .q(pwm[k]));
        end
    endgenerate
endmodule
