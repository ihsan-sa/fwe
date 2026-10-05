# fpga-build

`fpga_build.py --synth-only` lints the core (Verilator -Wall) and synthesises
it for the board's family at `gateware.json`'s geometry; the cell counts are
its utilisation estimate. Read them against the part.

Without `--synth-only` it goes on to the bitstream, which is not automated
yet: it refuses (exit 2) and names the first thing missing, `board`, then
nextpnr for the family, then the board top. Once the first two hold, write
the board top in `firmware/vendor/<family>/`, never in `rtl/`:

- `pwm8_clocks.v`: the PLL from the reference clock to the serialiser's edge
  clock (line rate / 2 for a DDR gearbox) and the core clock (line rate / W),
  plus a reset held until lock. Report the f_rf the PLL actually gives.
- `pwm8_top.v`: clocks, `pwm8_ctrl` with `CPB` = fabric clock / baud, and
  one `pwm8_serdes` per pin, channel k on `pwm_pins[k]`.
- the pin constraints from `board` (the I/O standard on every PWM pin), then
  place and route at the fabric clock, pack, and add those steps to the
  script so the next build runs them.

A timing failure at the fabric clock is a finding with its slack, not a
reason to drop N.
