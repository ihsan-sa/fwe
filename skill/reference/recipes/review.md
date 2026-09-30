# review

Run the pin-map check, the build and the host tests, then read the firmware
against this list and report findings (file:line, what, why):

- Every pin, channel and scale factor comes from `gen/board_pins.h`.
- Gate pins are driven low as GPIO before the timer exists; TIM1 comes up
  with MOE=0 and idle-low outputs; break inputs are wired.
- Fault paths: OV, UV, over-current (hardware and software) each latch,
  clear MOE at once, light the fault LED and emit an `EVT`.
- The console replies exactly one `OK`/`ERR` line per command and refuses
  `arm`/`duty` while faulted or disarmed.
- Watchdog is fed only from the main loop.
- Say which of these were checked by a test, by simulation, or only by
  reading.
