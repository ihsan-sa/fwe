# stage

Write or extend a firmware stage. Stages run in order and each must build,
pass its host tests and keep every safety default before the next starts.

1. **bringup**: clocks, LEDs, UART console (protocol in `reference/manifest.md`),
   ADC calibration and current-sense offsets with the bridge off, gate driver
   armed with PWM at 0 duty, fault handling.
2. **motor**: sensored six-step from the Halls first; FOC (Clarke/Park, PI
   current loops, SVPWM) after six-step is verified on hardware.

Rules for any stage:
- Math goes in `control/` (pure C, no registers) with host tests; register
  code goes in `src/`.
- Pins, ADC channels and scaling come from `gen/board_pins.h`, never typed.
- The safety defaults in `reference/design.md` stay true: PWM off at reset,
  hardware and software current limits, OV/UV trip, watchdog, a latched fault
  refuses `arm`/`duty` until `clear`.
- Declare any new console command on its dispatch line in `src/console.c`,
  `/* fwe-cmd args="..." safe=yes|no */`, with `safe=no` if it can energise the
  bridge; fw_manifest.py carries both into the manifest's `commands`.
- Bump `--stage` in the build and the manifest's `stage`.
