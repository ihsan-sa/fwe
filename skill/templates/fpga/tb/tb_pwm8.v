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
    pwm8_ctrl #(.CH(CH), .N(N), .W(W), .PW(PW), .CPB(CPB)) dut (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .word(word), .period_start(period_start));
endmodule
