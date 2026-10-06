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
// start, so an outphasing change never shows half applied. trim is each
// channel's coarse skew calibration in whole steps (< N): it delays the
// channel by adding to its phase, mod N, and loads with the same commit. Enable turns the
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
    input  [CH*PW-1:0]       trim,      // channel k at [k*PW +: PW], < N
    output reg [CH*W-1:0]    word,      // channel k at [k*W +: W]
    output reg               period_start,
    output reg               pending,   // a commit waits for the period start
    output reg               applied    // one clock: the shadows just loaded
);
    localparam WORDS = N / W;

    generate
        if (N % W != 0 || N >= (1 << PW)) begin : bad_params
            pwm8_core_needs_N_multiple_of_W_and_N_below_2_pow_PW bad ();
        end
    endgenerate

    // Timed at the ECP5 core clock (190 MHz), so no bit does a modulo: pos_k
    // is where channel k's own period stands at the first step of the word
    // being built, (widx*W - phase_k) mod N, kept by adding W each clock.
    // Step pos_k + j is high when it is below duty, or past N and below
    // N + duty (the wrap).
    reg [PW-1:0] widx;              // word index in the period
    reg [PW-1:0] pos  [0:CH-1];
    reg [PW:0]   du_a [0:CH-1];
    reg [PW+1:0] dn_a [0:CH-1];     // N + duty
    reg          en_a;
    wire         last = (widx == WORDS - 1);

    integer k, j;
    reg [PW+1:0]   d;
    reg [CH*W-1:0] next;
    always @(*) begin
        for (k = 0; k < CH; k = k + 1)
            for (j = 0; j < W; j = j + 1) begin
                d = pos[k] + j;
                next[k*W + j] = en_a && enable && (d < du_a[k] || (d >= N && d < dn_a[k]));
            end
    end

    // each channel's phase plus its coarse trim, mod N (both are < N), and
    // the pos a new phase starts its period at, (N - that) mod N. Registered
    // in two steps: they follow UART writes, and a commit comes bytes later.
    integer i;
    reg [PW:0]   s [0:CH-1];
    reg [PW-1:0] ph_t  [0:CH-1];
    reg [PW-1:0] start [0:CH-1];
    always @(*)
        for (i = 0; i < CH; i = i + 1)
            s[i] = phase[i*PW +: PW] + trim[i*PW +: PW];
    always @(posedge clk)
        for (i = 0; i < CH; i = i + 1) begin
            ph_t[i] <= (s[i] >= N) ? s[i] - N : s[i];
            start[i] <= (ph_t[i] == 0) ? 0 : N - ph_t[i];
        end

    always @(posedge clk) begin
        if (rst) begin
            widx <= 0;
            en_a <= 1'b0;
            pending <= 1'b0;
            word <= 0;
            period_start <= 1'b0;
            applied <= 1'b0;
            for (k = 0; k < CH; k = k + 1) begin
                pos[k] <= 0;
                du_a[k] <= 0;
                dn_a[k] <= N;
            end
        end else begin
            word <= next;
            period_start <= (widx == 0);
            widx <= last ? 0 : widx + 1;
            en_a <= enable && (en_a || last);
            pending <= (commit || pending) && !last;
            applied <= last && (pending || commit);
            for (k = 0; k < CH; k = k + 1)
                if (last && (pending || commit)) begin
                    pos[k] <= start[k];
                    du_a[k] <= {1'b0, duty[k*PW +: PW]};
                    dn_a[k] <= N + duty[k*PW +: PW];
                end else begin
                    pos[k] <= (pos[k] + W >= N) ? pos[k] + W - N : pos[k] + W;
                end
        end
    end
endmodule
