# pinmap

`pinmap.py --workspace <board>` writes `firmware/pinmap.json` and
`firmware/gen/board_pins.h` from the board's netlist. `--check` writes
nothing and exits 1 on drift; `fw_build.py` runs it first.

- A finding (unclassified pin, analog pin with no ADC channel, a timer group
  with no common timer) is reported, never guessed around. If the board is
  wrong, it is an hwde finding for the board, not a firmware workaround.
- After regenerating, diff the header: a moved pin or changed divider must
  be read, because the firmware may use the old meaning.
- A new net name the ROLES table does not know: extend ROLES in pinmap.py
  with a test in the repo's tests/test_pinmap.py.
