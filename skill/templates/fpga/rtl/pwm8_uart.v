// pwm8_uart - 8N1 UART receiver and transmitter, CPB clocks per bit.
module pwm8_uart_rx #(parameter CPB = 1062) (
    input            clk,
    input            rst,
    input            rx,
    output reg [7:0] data,
    output reg       valid
);
    reg [1:0]  sync;
    reg [15:0] cnt;
    reg [3:0]  bitn;
    reg        busy;
    always @(posedge clk) begin
        sync <= {sync[0], rx};
        valid <= 1'b0;
        if (rst) begin
            sync <= 2'b11;
            busy <= 1'b0;
        end else if (!busy) begin
            if (!sync[1]) begin             // start bit: sample mid-bit from here
                busy <= 1'b1;
                cnt <= CPB / 2;
                bitn <= 0;
            end
        end else if (cnt != 0) begin
            cnt <= cnt - 1;
        end else begin
            cnt <= CPB - 1;
            bitn <= bitn + 1;
            if (bitn == 0) begin
                if (sync[1]) busy <= 1'b0;  // a glitch, not a start bit
            end else if (bitn <= 8) begin
                data <= {sync[1], data[7:1]};
            end else begin
                busy <= 1'b0;
                valid <= sync[1];           // a missing stop bit drops the byte
            end
        end
    end
endmodule

module pwm8_uart_tx #(parameter CPB = 1062) (
    input        clk,
    input        rst,
    input  [7:0] data,
    input        send,
    output       tx,
    output       busy
);
    reg [9:0]  sh;
    reg [15:0] cnt;
    reg [3:0]  left;
    assign tx = sh[0];
    assign busy = (left != 0);
    always @(posedge clk) begin
        if (rst) begin
            sh <= 10'h3ff;
            left <= 0;
        end else if (left == 0) begin
            if (send) begin
                sh <= {1'b1, data, 1'b0};
                cnt <= CPB - 1;
                left <= 10;
            end
        end else if (cnt != 0) begin
            cnt <= cnt - 1;
        end else begin
            sh <= {1'b1, sh[9:1]};
            cnt <= CPB - 1;
            left <= left - 1;
        end
    end
endmodule
