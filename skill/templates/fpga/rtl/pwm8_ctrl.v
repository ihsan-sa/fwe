// pwm8_ctrl - the board-independent gateware: UART register access over
// pwm8_core and pwm8_taps. A board top adds the clocking and one pwm8_serdes
// per channel, whose delay line takes this module's dly_* outputs.
//
// Protocol (8N1 at the baud CPB sets), reference/fpga.md has the full table:
//   'W' addr data -> 'K', or 'E' when addr is read-only/unknown or data out of range
//   'R' addr      -> the register's byte ('E' for an unknown addr)
//   any other first byte -> '?'
// Registers: 0x00 ID (0xF8), 0x01 CTRL (bit0 enable rw, bit1 commit w,
// bit2 pending r, bit3 taps moving r), 0x02 N, 0x03 W, 0x04 CH, 0x05 fine
// taps (128), 0x10+k phase k (< N), 0x18+k duty k (<= N), 0x20+k coarse
// trim k (< N steps), 0x28+k fine trim k (< 128 taps). All four take effect
// on a commit; the fine trim then walks its delay line while bit3 is set.
module pwm8_ctrl #(
    parameter CH  = 8,
    parameter N   = 72,
    parameter W   = 8,
    parameter PW  = 7,
    parameter CPB = 1062
) (
    input              clk,
    input              rst,
    input              uart_rx,
    output             uart_tx,
    output [CH*W-1:0]  word,
    output             period_start,
    output [CH-1:0]    dly_loadn,       // to each channel's delay line
    output [CH-1:0]    dly_move,
    output [CH-1:0]    dly_dir
);
    localparam [7:0] ID = 8'hF8;
    localparam       TB = 7;            // fine trim bits: 128 taps

    wire [7:0] rx_data;
    wire       rx_valid;
    reg  [7:0] tx_data;
    reg        tx_send;
    pwm8_uart_rx #(.CPB(CPB)) urx (.clk(clk), .rst(rst), .rx(uart_rx),
                                   .data(rx_data), .valid(rx_valid));
    /* verilator lint_off PINCONNECTEMPTY */ // replies never overlap: one per >= 2 bytes in
    pwm8_uart_tx #(.CPB(CPB)) utx (.clk(clk), .rst(rst), .data(tx_data),
                                   .send(tx_send), .tx(uart_tx), .busy());
    /* verilator lint_on PINCONNECTEMPTY */

    // the registers, one array per kind, indexed by the address's low 3 bits
    // (CH <= 8), flattened for the core
    reg [PW-1:0] phase_r [0:CH-1];
    reg [PW-1:0] duty_r  [0:CH-1];
    reg [PW-1:0] trim_r  [0:CH-1];
    reg [TB-1:0] fine_r  [0:CH-1];
    wire [CH*PW-1:0] phase, duty, trim;
    wire [CH*TB-1:0] fine;
    genvar g;
    generate
        for (g = 0; g < CH; g = g + 1) begin : flat
            assign phase[g*PW +: PW] = phase_r[g];
            assign duty[g*PW +: PW] = duty_r[g];
            assign trim[g*PW +: PW] = trim_r[g];
            assign fine[g*TB +: TB] = fine_r[g];
        end
    endgenerate
    reg             enable, commit;
    wire            pending, applied, moving;
    pwm8_core #(.CH(CH), .N(N), .W(W), .PW(PW)) core (
        .clk(clk), .rst(rst), .enable(enable), .commit(commit),
        .phase(phase), .duty(duty), .trim(trim), .word(word),
        .period_start(period_start), .pending(pending), .applied(applied));
    pwm8_taps #(.CH(CH), .TB(TB)) taps (
        .clk(clk), .rst(rst), .load(applied), .target(fine),
        .loadn(dly_loadn), .move(dly_move), .direction(dly_dir), .moving(moving));

    reg [1:0] st;               // 0 idle, 1 want addr, 2 want data
    reg       is_write;
    reg [7:0] addr;

    localparam [7:0] N8 = N, W8 = W, CH8 = CH;
    localparam [7:0] TAPS8 = 1 << TB;

    // the read mux, registered: rx_data holds still for a whole bit time
    // after rx_valid, so the reply uses rd_* one clock later (valid_d)
    wire [2:0] ri = rx_data[2:0];
    wire       in_ch = (rx_data[2:0] < CH);
    reg        rd_ok, valid_d;
    reg [7:0]  rd_byte;
    always @(posedge clk) begin
        valid_d <= rx_valid;
        rd_ok <= 1'b1;
        rd_byte <= 8'h00;
        case (rx_data[7:3])
            5'h00: case (rx_data[2:0])
                       3'd0: rd_byte <= ID;
                       3'd1: rd_byte <= {4'b0, moving, pending, 1'b0, enable};
                       3'd2: rd_byte <= N8;
                       3'd3: rd_byte <= W8;
                       3'd4: rd_byte <= CH8;
                       3'd5: rd_byte <= TAPS8;
                       default: rd_ok <= 1'b0;
                   endcase
            5'h02: begin rd_byte <= phase_r[ri]; rd_ok <= in_ch; end
            5'h03: begin rd_byte <= duty_r[ri];  rd_ok <= in_ch; end
            5'h04: begin rd_byte <= trim_r[ri];  rd_ok <= in_ch; end
            5'h05: begin rd_byte <= fine_r[ri];  rd_ok <= in_ch; end
            default: rd_ok <= 1'b0;
        endcase
    end

    // the write side: wa is the register kind and channel of addr
    wire [2:0] wi = addr[2:0];
    wire       wch = (addr[2:0] < CH);
    integer k;
    always @(posedge clk) begin
        tx_send <= 1'b0;
        commit <= 1'b0;
        if (rst) begin
            st <= 0;
            enable <= 1'b0;
            for (k = 0; k < CH; k = k + 1) begin
                phase_r[k] <= 0;
                duty_r[k] <= 0;
                trim_r[k] <= 0;
                fine_r[k] <= 0;
            end
        end else if (valid_d) begin
            case (st)
                0: if (rx_data == "W" || rx_data == "R") begin
                       is_write <= (rx_data == "W");
                       st <= 1;
                   end else begin
                       tx_data <= "?";
                       tx_send <= 1'b1;
                   end
                1: if (is_write) begin
                       addr <= rx_data;
                       st <= 2;
                   end else begin
                       tx_data <= rd_ok ? rd_byte : "E";
                       tx_send <= 1'b1;
                       st <= 0;
                   end
                default: begin
                    st <= 0;
                    tx_send <= 1'b1;
                    tx_data <= "K";
                    if (addr == 8'h01) begin
                        enable <= rx_data[0];
                        commit <= rx_data[1];
                    end else if (addr[7:3] == 5'h02 && wch && rx_data < N)
                        phase_r[wi] <= rx_data;
                    else if (addr[7:3] == 5'h03 && wch && rx_data <= N)
                        duty_r[wi] <= rx_data;
                    else if (addr[7:3] == 5'h04 && wch && rx_data < N)
                        trim_r[wi] <= rx_data;
                    else if (addr[7:3] == 5'h05 && wch && rx_data < TAPS8)
                        fine_r[wi] <= rx_data;
                    else
                        tx_data <= "E";
                end
            endcase
        end
    end
endmodule
