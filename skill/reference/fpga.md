# FPGA gateware (pwm8)

The FPGA target writes gateware for an off-the-shelf dev board. The first
design, `pwm8`, drives eight PWM outputs for the 13.56 MHz RF inverter test
system, each with its own phase in steps of 1 / (N x f_rf), about 1 ns. The
outputs feed the output board's 50 ohm drivers, never the load.

## Shape

- `rtl/pwm8_core.v`: one word of W steps per channel per fabric clock.
  Channel k is high on step t when (t - phase_k) mod N < duty_k. Phase and
  duty are shadows that a commit loads for every channel at the next period
  start.
- `rtl/pwm8_ctrl.v` + `rtl/pwm8_uart.v`: the UART register protocol below.
- `vendor/<family>/`: the only board-specific code: the serialiser wrapper
  `pwm8_serdes` (ECP5: ODDRX2F, W = 4), and later the clocks and the top.
- `tb/`: the cocotb bench, run by /vde's cocotblib. It never reads `vendor/`.
- `gateware.json`: geometry (`f_rf_hz`, `steps_per_period` N, `word_bits` W,
  `uart_baud`) and `board`, filled from the handoff README.

The template's geometry is N = 72, W = 8 (1.024 ns steps at 976 Mbit/s,
122 MHz fabric). ECP5's gearbox tops out near 800 Mbit/s, so an ECP5 board
runs N = 56, W = 4 (1.32 ns steps) unless it adds fine output delay.

## UART protocol `fwe-pwm8-reg/1`

8N1 at `uart_baud`. Bytes, not text:

| send | reply |
|---|---|
| `W` addr value | `K`, or `E` if addr is read-only or unknown or value is out of range |
| `R` addr | the value, or `E` for an unknown addr |
| anything else first | `?` |

| addr | name | access | meaning |
|---|---|---|---|
| 0x00 | id | r | 0xF8 |
| 0x01 | ctrl | rw | bit0 enable (off at once, on at a period start); bit1 commit (write only); bit2 pending (read only) |
| 0x02 | steps_per_period | r | N |
| 0x03 | word_bits | r | W |
| 0x04 | channels | r | 8 |
| 0x10+k | phase k | rw | 0..N-1 steps |
| 0x18+k | duty k | rw | 0..N steps (0 always low, N always high) |

To outphase: write every phase and duty, then `W 0x01 0x03` (enable and
commit). The change lands for all channels at the same period start.

## Manifest `fwe-fpga-manifest/1`

`fpga_manifest.py` writes `firmware/fwe-manifest.json`, the same path as the
MCU manifest so /npie finds it in one place; `schema` and `kind: "fpga"`
tell the two apart. Keys: `board`, `design`, `version`, `fpga` (model,
vendor, part, package, speed), `clock`, `artifact` (bitstream and sha256,
null until built), `program.commands.openFPGALoader`, `geometry` (f_rf_hz,
channels, steps_per_period, word_bits, step_s, line_rate_bps), `outputs`
(channel, pin, io_standard), `uart`, `protocol` (the framing above),
`registers` (the table above with ranges), `safety`, and `verified` (sim,
synth, bitstream, hardware: evidence on the current design, hardware always
false).
