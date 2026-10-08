# Golden pin map: PCB-0026-A (STM32G474, HRTIM boost)

`PCB-0026-A_gan-boost-48v.net` is a copy of the boards repo's
`PCB-0026-A_gan-boost-48v/kicad/PCB-0026-A_gan-boost-48v.net` at boards commit
d394f58c (PR #58). `PCB-0026-A.pinmap.json` and `PCB-0026-A.board_pins.h` are
what `pinmap.py` makes of it.

`tests/test_pinmap.py::test_golden_g474_boost_pinmap` rebuilds both from the
netlist and compares, so a change to pinmap.py or `reference/mcu/stm32g474.json`
that moves this board's map fails `make check`. When the change is meant,
regenerate the two outputs with pinmap.py on a scratch copy of the workspace
and say why in the PR; never edit them by hand.
