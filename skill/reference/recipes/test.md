# test

`fw_test.py --workspace <board> [--only <module>]` compiles each
`firmware/tests/test_*.c` with the host compiler over `control/*.c` and runs it.

- These prove the control math on the host: transforms, duty, scaling,
  fault latching. They prove nothing about registers, timing or the analog
  front end, and a report must say so.
- A new module in `control/` gets a `tests/test_<module>.c` in the same
  change. Board-derived constants are checked in one test that includes
  `gen/board_pins.h`; the others must not depend on the board.
