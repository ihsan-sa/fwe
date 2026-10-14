# esp32-pinmap

The same `pinmap.py --workspace <board>` as `pinmap`: an ESP32 module on the
netlist makes it write squeezelite-esp32's NVS settings
(`firmware/gen/nvs_config.csv`) and `gen/board_pins.h` instead of timers and
ADC channels. `--check` writes nothing and exits 1 on drift. Read
`pinmap.md`'s ESP32 paragraph for the keys and the findings; everything there
holds here.
