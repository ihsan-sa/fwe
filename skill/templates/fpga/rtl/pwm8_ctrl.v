// pwm8_ctrl - the board-independent gateware: UART register access over
// pwm8_core. A board top adds the clocking and one pwm8_serdes per channel.
//
// Protocol (8N1 at the baud CPB sets), reference/fpga.md has the full table:
//   'W' addr data -> 'K', or 'E' when addr is read-only/unknown or data out of range
//   'R' addr      -> the register's byte ('E' for an unknown addr)
//   any other first byte -> '?'
// Registers: 0x00 ID (0xF8), 0x01 CTRL (bit0 enable rw, bit1 commit w,
// bit2 pending r), 0x02 N, 0x03 W, 0x04 CH, 0x10+k phase k (< N),
// 0x18+k duty k (<= N). Phase and duty take effect on a commit.
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
    output             period_start
);
    localparam [7:0] ID = 8'hF8;

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

    reg [CH*PW-1:0] phase, duty;
    reg             enable, commit;
    wire            pending;
    pwm8_core #(.CH(CH), .N(N), .W(W), .PW(PW)) core (
        .clk(clk), .rst(rst), .enable(enable), .commit(commit),
        .phase(phase), .duty(duty), .word(word),
        .period_start(period_start), .pending(pending));

    reg [1:0] st;               // 0 idle, 1 want addr, 2 want data
    reg       is_write;
    reg [7:0] addr;

    localparam [7:0] N8 = N, W8 = W, CH8 = CH;

    // the read mux: rd_ok says addr names a register, rd_byte is its value
    reg       rd_ok;
    reg [7:0] rd_byte;
    always @(*) begin
        rd_ok = 1'b1;
        rd_byte = 8'h00;
        if (rx_data == 8'h00) rd_byte = ID;
        else if (rx_data == 8'h01) rd_byte = {5'b0, pending, 1'b0, enable};
        else if (rx_data == 8'h02) rd_byte = N8;
        else if (rx_data == 8'h03) rd_byte = W8;
        else if (rx_data == 8'h04) rd_byte = CH8;
        else if (rx_data >= 8'h10 && rx_data < 8'h10 + CH) rd_byte = phase[(rx_data - 8'h10)*PW +: PW];
        else if (rx_data >= 8'h18 && rx_data < 8'h18 + CH) rd_byte = duty[(rx_data - 8'h18)*PW +: PW];
        else rd_ok = 1'b0;
    end

    always @(posedge clk) begin
        tx_send <= 1'b0;
        commit <= 1'b0;
        if (rst) begin
            st <= 0;
            enable <= 1'b0;
            phase <= 0;
            duty <= 0;
        end else if (rx_valid) begin
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
                    end else if (addr >= 8'h10 && addr < 8'h10 + CH && rx_data < N)
                        phase[(addr - 8'h10)*PW +: PW] <= rx_data;
                    else if (addr >= 8'h18 && addr < 8'h18 + CH && rx_data <= N)
                        duty[(addr - 8'h18)*PW +: PW] <= rx_data;
                    else
                        tx_data <= "E";
                end
            endcase
        end
    end
endmodule
