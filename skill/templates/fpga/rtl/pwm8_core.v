// pwm8_core - CH channels of PWM at one-step resolution, one word per clock.
//
// A period is N steps; one clock emits W steps per channel (word bit 0 leaves
// the serialiser first), so the fabric clock is N*f_rf/W and the line rate
// N*f_rf. At f_rf = 13.56 MHz and N = 72 a step is 1.024 ns. N must be a
// multiple of W so every period starts on a word.
//
// Channel k is high on step t of the period when (t - phase_k) mod N <
// duty_k: phase moves the rising edge in whole steps, duty is the high time in
// steps (0 = always low, N = always high). The phase and duty inputs are
// shadows: a commit pulse loads all channels together at the next period
// start, so an outphasing change never shows half applied. Enable turns the
// outputs off at once and back on only at a period start; outputs are low
// from reset.
module pwm8_core #(
    parameter CH = 8,
    parameter N  = 72,
    parameter W  = 8,
    parameter PW = 7            // bits for a phase or duty value, holds N
) (
    input                    clk,
    input                    rst,
    input                    enable,
    input                    commit,
    input  [CH*PW-1:0]       phase,     // channel k at [k*PW +: PW], < N
    input  [CH*PW-1:0]       duty,      // channel k at [k*PW +: PW], <= N
    output reg [CH*W-1:0]    word,      // channel k at [k*W +: W]
    output reg               period_start,
    output reg               pending    // a commit waits for the period start
);
    localparam WORDS = N / W;

    generate
        if (N % W != 0 || N >= (1 << PW)) begin : bad_params
            pwm8_core_needs_N_multiple_of_W_and_N_below_2_pow_PW bad ();
        end
    endgenerate

    reg [PW-1:0] widx;              // word index in the period
    reg [PW-1:0] ph_a [0:CH-1];
    reg [PW:0]   du_a [0:CH-1];
    reg          en_a;
    wire         last = (widx == WORDS - 1);

    // the next word: bit j of channel k is step widx*W + j of the period
    integer k, j;
    reg [PW+1:0]   t, d;
    reg [CH*W-1:0] next;
    always @(*) begin
        for (k = 0; k < CH; k = k + 1)
            for (j = 0; j < W; j = j + 1) begin
                t = widx * W + j;
                d = (t >= ph_a[k]) ? t - ph_a[k] : t + N - ph_a[k];
                next[k*W + j] = en_a && enable && (d < du_a[k]);
            end
    end

    always @(posedge clk) begin
        if (rst) begin
            widx <= 0;
            en_a <= 1'b0;
            pending <= 1'b0;
            word <= 0;
            period_start <= 1'b0;
            for (k = 0; k < CH; k = k + 1) begin
                ph_a[k] <= 0;
                du_a[k] <= 0;
            end
        end else begin
            word <= next;
            period_start <= (widx == 0);
            widx <= last ? 0 : widx + 1;
            en_a <= enable && (en_a || last);
            pending <= (commit || pending) && !last;
            if (last && (pending || commit))
                for (k = 0; k < CH; k = k + 1) begin
                    ph_a[k] <= phase[k*PW +: PW];
                    du_a[k] <= {1'b0, duty[k*PW +: PW]};
                end
        end
    end
endmodule
