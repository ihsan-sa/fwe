// pwm8_clocks (ECP5) - from the board's reference clock to the gearbox's
// edge clock and the core clock, through two cascaded EHXPLLL (one PLL
// cannot land on 13.56 MHz x 56 from 12 MHz).
//
//   PLL1: ref / P1_CLKI * P1_FB * P1_OP / P1_OS   (12 MHz -> 540 VCO -> 67.5 MHz)
//   PLL2: PLL1 / P2_CLKI * P2_FB * P2_OP / P2_OS  (-> 759.375 VCO -> 379.6875 MHz)
//   eclk = PLL2 CLKOS through ECLKSYNCB, sclk = eclk / 2 (CLKDIVF)
//
// Feedback is CLKOP in both, so VCO = PFD x CLKFB_DIV x CLKOP_DIV. The
// start-up is the GDDRX sync of TN-02035: hold the divider and the gearboxes
// in reset until both PLLs lock, stop eclk, release the resets, start eclk,
// so every ODDRX2F and CLKDIVF leave reset on the same edge. It runs on the
// reference clock, which runs from power-up. `rst` (sclk domain) holds the
// core until all that is done.
module pwm8_clocks #(
    parameter P1_CLKI = 1, P1_FB = 1, P1_OP = 45, P1_OS = 8,
    parameter P2_CLKI = 4, P2_FB = 1, P2_OP = 45, P2_OS = 2
) (
    input      ref_clk,
    output     eclk,
    output     sclk,
    output     gddr_rst,     // ODDRX2F reset
    output reg rst           // core reset, sclk domain
);
    wire op1, os1, lock1, op2, os2, lock2;
    /* verilator lint_off PINCONNECTEMPTY */
    EHXPLLL #(
        .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"), .STDBY_ENABLE("DISABLED"),
        .DPHASE_SOURCE("DISABLED"), .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
        .CLKI_DIV(P1_CLKI), .CLKFB_DIV(P1_FB), .FEEDBK_PATH("CLKOP"),
        .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(P1_OP), .CLKOP_CPHASE(P1_OP - 1), .CLKOP_FPHASE(0),
        .CLKOS_ENABLE("ENABLED"), .CLKOS_DIV(P1_OS), .CLKOS_CPHASE(P1_OS - 1), .CLKOS_FPHASE(0)
    ) pll1 (
        .CLKI(ref_clk), .CLKFB(op1), .CLKOP(op1), .CLKOS(os1), .LOCK(lock1),
        .RST(1'b0), .STDBY(1'b0), .PHASESEL0(1'b0), .PHASESEL1(1'b0), .PHASEDIR(1'b0),
        .PHASESTEP(1'b0), .PHASELOADREG(1'b0), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
        .ENCLKOS(1'b0), .ENCLKOS2(1'b0), .ENCLKOS3(1'b0), .CLKOS2(), .CLKOS3(), .CLKINTFB(),
        .INTLOCK(), .REFCLK());
    EHXPLLL #(
        .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"), .STDBY_ENABLE("DISABLED"),
        .DPHASE_SOURCE("DISABLED"), .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
        .CLKI_DIV(P2_CLKI), .CLKFB_DIV(P2_FB), .FEEDBK_PATH("CLKOP"),
        .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(P2_OP), .CLKOP_CPHASE(P2_OP - 1), .CLKOP_FPHASE(0),
        .CLKOS_ENABLE("ENABLED"), .CLKOS_DIV(P2_OS), .CLKOS_CPHASE(P2_OS - 1), .CLKOS_FPHASE(0)
    ) pll2 (
        .CLKI(os1), .CLKFB(op2), .CLKOP(op2), .CLKOS(os2), .LOCK(lock2),
        .RST(!lock1), .STDBY(1'b0), .PHASESEL0(1'b0), .PHASESEL1(1'b0), .PHASEDIR(1'b0),
        .PHASESTEP(1'b0), .PHASELOADREG(1'b0), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
        .ENCLKOS(1'b0), .ENCLKOS2(1'b0), .ENCLKOS3(1'b0), .CLKOS2(), .CLKOS3(), .CLKINTFB(),
        .INTLOCK(), .REFCLK());
    /* verilator lint_on PINCONNECTEMPTY */

    // GDDRX sync on the reference clock: 0 wait lock, 1 stop, 2 release, 3 run
    reg [1:0] lk = 2'b00;
    reg [1:0] st = 2'd0;
    reg [3:0] n = 4'd0;
    reg       stop = 1'b0, hold = 1'b1;
    always @(posedge ref_clk) begin
        lk <= {lk[0], lock1 & lock2};
        n <= n + 1'b1;
        if (!lk[1]) begin
            st <= 2'd0; stop <= 1'b0; hold <= 1'b1; n <= 4'd0;
        end else if (n == 4'd15) begin
            case (st)
                2'd0: begin stop <= 1'b1; st <= 2'd1; end
                2'd1: begin hold <= 1'b0; st <= 2'd2; end
                2'd2: begin stop <= 1'b0; st <= 2'd3; end
                default: ;
            endcase
        end
    end
    assign gddr_rst = hold;

    ECLKSYNCB es (.ECLKI(os2), .STOP(stop), .ECLKO(eclk));
    /* verilator lint_off PINCONNECTEMPTY */
    CLKDIVF #(.DIV("2.0")) div (.CLKI(eclk), .RST(hold), .ALIGNWD(1'b0), .CDIVX(sclk));
    /* verilator lint_on PINCONNECTEMPTY */

    // the core leaves reset a few sclk edges after eclk runs again
    reg [3:0] rs = 4'hF;
    always @(posedge sclk or posedge hold)
        if (hold) rs <= 4'hF;
        else rs <= {rs[2:0], stop};
    always @(posedge sclk) rst <= rs[3];
endmodule
