# /fwe design

/fwe is a firmware engineer for the boards hwde designs. It writes, builds and
tests firmware for one board at a time, inside that board's workspace in the
boards repo, as `firmware/`. It never touches the board's design files; it
reads what hwde produced and derives everything board-specific from it.

## Goal and boundaries

- **In:** an hwde board workspace (`$HWDE_BOARDS_ROOT/<PN>_<name>`, default
  `~/dev/boards`), its
  netlist (`kicad/<ws>.net`), `requirements.md` and `research/`.
- **Out:** `firmware/` in that workspace: a CMake project, a generated pin
  map, host unit tests, a build, a simulation smoke log, and the firmware
  manifest `/npie` reads to flash and drive the board (`manifest.md`).
- **Not /fwe's:** flashing real hardware, lab instruments, anything on the
  owner's laptop (that is /npie's, behind the owner's approval), editing the
  schematic or layout (a pin conflict is a finding for hwde, not a rewire).
- **User space only.** Every tool lives under `~/.local/fwe-tools`, fetched by
  `scripts/fwe_setup.py` from the pins in `reference/toolchain.lock.json`.
  Anything that needs root, a container or apt is a question to the owner.

## The board is the source of truth

`scripts/pinmap.py` reads the netlist and writes `firmware/pinmap.json` and
`firmware/gen/board_pins.h`. Every MCU pin the firmware touches comes from
there, by net name, so firmware cannot drift from the board: if the board is
re-spun and a net moves, `pinmap.py --check` fails the build until the
generated header is regenerated. It also resolves the analog scaling a
firmware needs from the parts on the nets (divider ratios, the INA240's gain
from its part suffix and its REF pins, the shunt value) so the constants are
derived, not typed.

Net roles are classified by name (the `ROLES` table in `pinmap.py`):
`INH*/INL*` gate-driver inputs, `ISENSE_*` phase current, `VSENSE_*` phase
voltage, `VBUS_SENSE`, `HALL_*`, `ENC_*`, `UART_TX/RX`, `LED_*`, `*_SW`
buttons, `SWDIO/SWCLK/SWO/NRST/BOOT0` debug (SWO must sit on a pin with SWO/TRACESWO at AF0,
else a `not_swo_pin` finding). A pin on a net with no role is
reported as `unclassified`, never guessed. Peripheral functions (timer
channels, USART, ADC channels, comparator inputs) come from the MCU's pin
table `reference/mcu/<family>.json`, extracted from the datasheet.

## Firmware shape (STM32G4, the first family)

- CMSIS register-level C (no HAL, no LL): the device header and core headers
  are the only vendor code, pinned in the lock. Small, auditable, and the
  host tests compile the same control sources with the host gcc.
- `firmware/` layout: `CMakeLists.txt`, `cmake/arm-gcc.cmake`,
  `src/` (startup, system clock, board, app), `control/` (pure C math, no
  register access: the part host tests exercise), `tests/` (host unit
  tests), `gen/` (generated from the board), `sim/` (Renode/QEMU scripts),
  `fwe-manifest.json`.
- Build: `-Wall -Wextra -Werror -Os -mcpu=cortex-m4 -mfpu=fpv4-sp-d16
  -mfloat-abi=hard`, outputs `.elf/.bin/.hex/.map` and a size report.

## Safety defaults (every motor board)

1. PWM off at reset: the gate-driver input pins are driven low as GPIO
   before the timer is configured, the timer comes up with MOE=0, and
   `BKIN`/comparator break sets outputs to their idle (low) state.
2. Current limit: a hardware trip (the G4 comparators on the current-sense
   pins feeding TIM1 break) plus a software limit in the control loop.
3. Overvoltage and undervoltage trip on the bus-voltage ADC, checked every
   control cycle; a trip latches a fault that only an explicit `clear`
   command resets.
4. A watchdog (IWDG) that resets into the safe state.
5. The UART console refuses `arm`/`run` while a fault is latched.

## Stages

1. **bringup:** clocks, LEDs, UART console, ADC offset calibration with the
   bridge off, gate driver armed with PWM at 0 duty, fault handling.
2. **motor:** sensored six-step from the Halls first (simplest thing that
   spins a motor safely), FOC (Clarke/Park, PI current loops, SVPWM) as the
   next step once six-step is verified on hardware.

## Verification ladder (say plainly what was only simulated)

| rung | what it proves | how |
|---|---|---|
| pinmap | firmware pins = board nets | `pinmap.py --check` |
| build | it compiles clean | cross build, warnings are errors |
| host tests | the control math is right | host gcc + unit tests |
| sim | it boots and talks | Renode (or QEMU) runs the ELF, script checks the UART banner |
| hardware | it works | /npie, through the manifest; not /fwe's |

Simulation proves the boot path, the console and the fault logic against
modelled peripherals only. It proves nothing about the analog front end,
the gate driver, timing on real silicon or the motor.

## Router

`scripts/task_router.py --task "<words>" --workspace <board>` picks one verb
and returns its recipe (`reference/recipes/<verb>.md`): `setup`, `pinmap`,
`scaffold`, `build`, `test`, `sim`, `manifest`, `stage` (write a firmware
stage), `review`. The scripts follow hwde's contract: argparse, JSON to
stdout or `--out`, exit 0 ok / 1 finding / 2 error, no prompts, ASCII output.
