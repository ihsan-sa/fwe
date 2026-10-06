# fpga-build

`fpga_build.py --synth-only` lints the core (Verilator -Wall) and synthesises
it for the board's family at `gateware.json`'s geometry; the cell counts are
its utilisation estimate. Read them against the part.

Without `--synth-only` it goes on to the bitstream (ECP5 so far). It
refuses (exit 2) and names the first thing missing: `board`, nextpnr-ecp5 and
ecppack, or `board.pll`. The board top is `vendor/ecp5/`, never `rtl/`:

- `pwm8_clocks.v`: two cascaded EHXPLLL from the reference clock to the
  edge clock (line rate / 2), ECLKSYNCB and CLKDIVF to the core clock
  (line rate / 4), and the GDDRX start-up (stop, release resets, start).
- `pwm8_serdes.v`: ODDRX2F then DELAYF per pin, the delay walked by the
  core's `pwm8_taps`.
- `pwm8_top.v`: clocks, `pwm8_ctrl` with `CPB` = core clock / baud, one
  `pwm8_serdes` per pin, channel k on `pwm_pins[k]`.

The script writes `build/pnr/pwm8.lpf` from `board`, places and routes with
the board's `nextpnr_args`, and checks that every pin got its output delay
and that every clock meets its constraint before ecppack writes
`build/pwm8.bit`. `clocking` in the result says what the PLLs really give:
on the EVN, a 1.3169 ns step and f_rf 19.75 ppm high of 13.56 MHz.

A timing failure at the core clock is a finding with its slack (exit 1,
`step` "timing"), not a reason to drop N. The core is written for it: no
bit does a modulo, and the register read-back is registered.
