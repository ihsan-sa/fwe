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
- An ESP32 module board (squeezelite-esp32) gets squeezelite's NVS config
  instead of timers and ADC channels: `gen/nvs_config.csv` holds the
  `config` namespace upstream reads (`dac_config`, `dac_controlset`,
  `set_GPIO`, `i2c_config`, `eth_config`, `rotary_config`, `display_config`,
  `spi_config`) and a `fwe` namespace for what only our components read
  (line-in ADC, amp warning pin, buttons). A part listed in
  `reference/esp32/codecs.json` places its control pins (enable, fault,
  mute) through its own pin names, whatever the net is called; the rest go
  by net name (fwelib/squeezelite.py ROLES). A codec whose I2C sequence is
  not checked against its datasheet (`verified: false`) is a
  `codec_unverified` finding: fill the sequence from the datasheet and set
  `verified` rather than flashing it. RMII pins taken by something else, an
  output on GPIO34-39, or a flash/PSRAM pin in use are findings too.
  The amp rail's current sense (a net like `AMP_ISNS`), which `fwe_pd_limit`
  reads, must sit on an ADC1 pin (GPIO32-39; ADC2 is Wi-Fi's) or it is an
  `isns_not_adc1` finding; its amp and shunt are read as on an STM32 board
  and land in `board_pins.h` as `RAIL_ISNS_ADC1_CH`, `RAIL_ISNS_REF_V` and
  `RAIL_ISNS_V_PER_A`.
