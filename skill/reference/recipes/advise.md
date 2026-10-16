# advise

`mcu_advice.py --workspace <board>` reads the board's draft netlist and writes
`firmware/mcu-advice.json` (`fwe-mcu-advice/1`): one item per thing hwde should
change while the board is still being drawn, each with its `topic` (debug,
reset, boot, uart, clock), `severity` (`must` or `should`), the pin, the net,
what to do (`says`) and why. It serves STM32 and classic ESP32 boards.

- Run it on hwde's draft, before layout, and hand the file to hwde; never edit
  the board's KiCad files yourself (SKILL.md rule 1).
- exit 1 -> at least one `must`: as drawn, the board can't be debugged, flashed
  or booted. Each `must` goes to hwde as a finding to fix before layout.
- exit 0 with `should` items -> pass them on; hwde decides.
- exit 2 -> no single netlist, no MCU it knows, or an ESP32-C3/S3 (refused).
- A pin the MCU table doesn't name isn't checked; no advice is not a review.
