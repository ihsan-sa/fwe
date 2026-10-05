# fpga-sim

`fpga_sim.py` builds `rtl/` and `tb/` under Icarus and runs every
`tb/test_*.py` through /vde's cocotblib (it re-execs into chip-flow's
`eda python`). The bench is board-independent: it never reads `vendor/`.
The tests rebuild each channel's serial stream from the core's words and
prove, in steps: outputs low from reset, the edge moves exactly one step per
phase count (across word boundaries and the period wrap), eight channels at
equal phase are identical and at set phases land exactly there, a commit
lands on a period start for all channels in the same period, duty limits and
range refusals, and disable is immediate.

A new behaviour gets its test in `tb/test_pwm8.py` before the RTL changes.
A failing test is fixed in the RTL, never by loosening the test. The result
is recorded in `build/sim.json` against a hash of the design, which the
manifest reads.
