# FPGA gateware (pwm8)

The FPGA target writes gateware for an off-the-shelf dev board. The first
design, `pwm8`, drives eight PWM outputs for the 13.56 MHz RF inverter test
system, each with its own phase in steps of 1 / (N x f_rf), about 1 ns. The
outputs feed the output board's 50 ohm drivers, never the load.

## Shape

- `rtl/pwm8_core.v`: one word of W steps per channel per fabric clock.
  Channel k is high on step t when (t - phase_k - trim_k) mod N < duty_k.
  Phase, duty and the coarse trim are shadows that a commit loads for every
  channel at the next period start.
- `rtl/pwm8_taps.v`: walks each pin's output delay line (DELAYF) to its fine
  trim, one tap per MOVE pulse, from the same commit.
- `rtl/pwm8_ctrl.v` + `rtl/pwm8_uart.v`: the UART register protocol below.
- `vendor/<family>/`: the only board-specific code. ECP5: `pwm8_clocks`
  (two PLLs, ECLKSYNCB, CLKDIVF, GDDRX start-up), `pwm8_serdes` (ODDRX2F
  then DELAYF, W = 4) and `pwm8_top`.
- `tb/`: the cocotb bench, run by /vde's cocotblib. It never reads `vendor/`;
  it models DELAYF as a tap count and turns taps into time itself.
- `gateware.json`: geometry (`f_rf_hz`, `steps_per_period` N, `word_bits` W,
  `uart_baud`), `board` (from a profile in `templates/fpga-boards/` or the
  handoff README) and `calibration` (per-channel `coarse` steps and `fine`
  taps, zeros until /npie measures the skew, and its `source`).

The template's geometry is N = 72, W = 8 (1.024 ns steps at 976 Mbit/s,
122 MHz fabric). ECP5's gearbox tops out near 800 Mbit/s, so an ECP5 board
runs N = 56, W = 4: on the LFE5UM5G-85F-EVN a 1.3169 ns step, a 189.84 MHz
core clock and f_rf 19.75 ppm high.

## Skew calibration

The channels reach the load up to 3.59 ns apart uncalibrated (the boards
seat's budget), against a 0.1 ns target. Each channel is held back by a trim
of whole coarse steps (added to its phase) plus DELAYF fine taps (~25 ps,
128 of them, 3.2 ns, more than one step). Every channel is trimmed to the
latest one, so the table is all delays, and zeros mean uncalibrated. /npie
measures the skew and the tap; the manifest's `calibration` carries the
table and the writes that load it. The taps as a general fine phase step on
top of the coarse one are a later stage.

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
| 0x01 | ctrl | rw | bit0 enable (off at once, on at a period start); bit1 commit (write only); bit2 pending (read only); bit3 taps moving (read only) |
| 0x02 | steps_per_period | r | N |
| 0x03 | word_bits | r | W |
| 0x04 | channels | r | 8 |
| 0x05 | fine_taps | r | 128 |
| 0x10+k | phase k | rw | 0..N-1 steps |
| 0x18+k | duty k | rw | 0..N steps (0 always low, N always high) |
| 0x20+k | trim_coarse k | rw | 0..N-1 steps of delay, lands on a commit |
| 0x28+k | trim_fine k | rw | 0..127 delay taps, walked after a commit while bit3 is set |

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
`registers` (the table above with ranges), `calibration` (`table` of
coarse and fine per channel, `load` as register writes, `then` the commit,
`step_s`, `tap_s_nominal`, `problems` for a value a register would refuse),
`safety`, and `verified` (sim, synth, bitstream, hardware: evidence on the
current design; bitstream only after timing was met; hardware always
false). `clock` gives what the PLLs really make (`fabric_hz`, `edge_hz`,
`f_rf_actual_hz`, `f_rf_error_ppm`) and `uart.note` what the board needs
before its UART pins work.
