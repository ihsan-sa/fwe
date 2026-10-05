# fpga-scaffold

`fpga_scaffold.py` copies `templates/fpga/` into the board's `firmware/` and
keeps every file already there. Then fill `gateware.json`'s `board` from the
boards seat's handoff, `firmware/README.md`: model, vendor, part, package,
speed grade, reference clock (Hz and pin), the eight PWM pins in channel
order, the I/O standard into the output board's drivers, the UART pins, and
the openFPGALoader board name. Copy values, never guess one: a field the
README does not give stays null and the build says so.

Set the geometry for the part: `steps_per_period` (N) times `f_rf_hz` is the
line rate, and `word_bits` (W) is the serialiser width per fabric clock.
N must be a multiple of W. ECP5's ODDRX2F gearbox is 4:1 with a 400 MHz edge
clock at most, so on ECP5 W = 4 and N = 56 (759 Mbit/s, 1.32 ns steps) is the
fastest in spec; 72 steps (1.02 ns) needs a ~1 Gbit/s serialiser such as an
Artix-7 OSERDESE2 at 8:1. Say which one the board gives, in steps and ns.
