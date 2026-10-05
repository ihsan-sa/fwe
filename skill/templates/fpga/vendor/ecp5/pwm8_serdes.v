// pwm8_serdes (ECP5) - one channel's word onto its pin through ODDRX2F, the
// ECP5 4:1 output gearbox: d[0] leaves first, eclk is the DDR edge clock
// (line rate / 2) and sclk = eclk / 2 (CLKDIVF) clocks the core. The core
// and its bench never see this file; a board top instantiates one per pin.
module pwm8_serdes #(parameter W = 4) (
    input          sclk,
    input          eclk,
    input          rst,
    input  [W-1:0] d,
    output         q
);
    generate
        if (W != 4) begin : bad_width
            pwm8_serdes_ecp5_needs_W_4 bad ();
        end
    endgenerate
    ODDRX2F oddr (.D0(d[0]), .D1(d[1]), .D2(d[2]), .D3(d[3]),
                  .SCLK(sclk), .ECLK(eclk), .RST(rst), .Q(q));
endmodule
