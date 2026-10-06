# fpga-review

Run the synth, the bench and the manifest check, then read the gateware
against this list and report findings (file:line, what, why):

- The core and bench have no vendor primitive and no pin: those live only in
  `vendor/<family>/` and `gateware.json`.
- Outputs are low from reset and on disable; enable and every phase or duty
  change take effect only at a period start, all channels together.
- An out-of-range phase, duty or trim is refused (`E`), never clamped; the
  trims land with a commit like phase and duty.
- The geometry the board runs (N, W, line rate) is what `gateware.json` and
  the manifest say, and the serialiser's first bit is word bit 0.
- The PLL's actual f_rf and the fabric timing slack are reported, and every
  PWM pin got its output delay (`output_delays` in the build result).
- Say which of these a test proved, which synthesis showed, and which were
  only read.
