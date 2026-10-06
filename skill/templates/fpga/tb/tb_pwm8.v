// tb_pwm8 - the board-independent bench top: pwm8_ctrl alone, driven by
// tb/test_pwm8.py. fpga_sim.py puts a generated file defining the GW_*
// macros (from gateware.json, with a short UART bit time) ahead of this one.
`ifndef GW_N
`define GW_N 72
`endif
`ifndef GW_W
`define GW_W 8
`endif
`ifndef GW_PW
`define GW_PW 7
`endif
`ifndef GW_CPB
`define GW_CPB 8
`endif
module tb_pwm8;
    localparam CH = 8, N = `GW_N, W = `GW_W, PW = `GW_PW, CPB = `GW_CPB;
    reg            clk = 1'b0;
    reg            rst = 1'b1;
    reg            uart_rx = 1'b1;
    wire           uart_tx;
    wire [CH*W-1:0] word;
    wire           period_start;
    // the geometry, readable from the test
    wire [7:0] p_n = N, p_w = W, p_cpb = CPB;
    wire [CH-1:0]  dly_loadn, dly_move, dly_dir;
    pwm8_ctrl #(.CH(CH), .N(N), .W(W), .PW(PW), .CPB(CPB)) dut (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .word(word), .period_start(period_start),
        .dly_loadn(dly_loadn), .dly_move(dly_move), .dly_dir(dly_dir));
    // each channel's delay line, as a tap count the test reads (tap_k)
    genvar g;
    generate
        for (g = 0; g < CH; g = g + 1) begin : line
            tb_delayf dl (.loadn(dly_loadn[g]), .move(dly_move[g]), .direction(dly_dir[g]));
        end
    endgenerate
endmodule

// tb_delayf - what the bench knows of ECP5's DELAYF: LOADN low puts the line
// back at DEL_VALUE (0), each rising MOVE edge moves one tap, DIRECTION 1
// toward less delay; it stops at 0 and 127 (CFLAG). The edge itself is not
// delayed here: the test turns the tap count into time.
module tb_delayf (
    input loadn,
    input move,
    input direction
);
    integer tap = 0;
    integer moves = 0;
    always @(negedge loadn) tap = 0;
    always @(posedge move)
        if (loadn) begin
            moves = moves + 1;
            if (direction && tap > 0) tap = tap - 1;
            else if (!direction && tap < 127) tap = tap + 1;
        end
endmodule
