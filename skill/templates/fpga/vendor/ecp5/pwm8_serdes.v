// pwm8_serdes (ECP5) - one channel's word onto its pin through ODDRX2F, the
// ECP5 4:1 output gearbox, then DELAYF, the pin's 128-tap output delay
// (about 25 ps a tap) that holds the channel's fine skew trim: d[0] leaves
// first, eclk is the DDR edge clock (line rate / 2) and sclk = eclk / 2
// (CLKDIVF) clocks the core. LOADN, MOVE and DIRECTION come from the core's
// pwm8_taps. The core and its bench never see this file; a board top
// instantiates one per pin.
module pwm8_serdes #(parameter W = 4) (
    input          sclk,
    input          eclk,
    input          rst,
    input  [W-1:0] d,
    input          loadn,
    input          move,
    input          direction,
    output         q
);
    generate
        if (W != 4) begin : bad_width
            pwm8_serdes_ecp5_needs_W_4 bad ();
        end
    endgenerate
    wire s;
    ODDRX2F oddr (.D0(d[0]), .D1(d[1]), .D2(d[2]), .D3(d[3]),
                  .SCLK(sclk), .ECLK(eclk), .RST(rst), .Q(s));
    /* verilator lint_off PINCONNECTEMPTY */
    DELAYF #(.DEL_MODE("USER_DEFINED"), .DEL_VALUE(0)) dly (
        .A(s), .LOADN(loadn), .MOVE(move), .DIRECTION(direction), .Z(q), .CFLAG());
    /* verilator lint_on PINCONNECTEMPTY */
endmodule
