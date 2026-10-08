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
- A converter board whose switches an HRTIM drives (nets `PWM_HI`/`PWM_LO`)
  gets both outputs of one HRTIM timer, and `fault_routes` names the
  comparator on each trip sense pin (`ISNS` over-current, `VOUT_SNS`
  over-voltage). The FLTn input that comparator reaches is read from the MCU
  table's `hrtim.fault_internal_sources`, and only once that table says it was
  verified against the reference manual; until then each route is a
  `fault_route_unverified` finding and `board_pins.h` carries no `TRIP_*_FLT`.
