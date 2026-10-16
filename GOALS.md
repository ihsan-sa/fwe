# fwe goals

`/fwe` is a Claude Code skill that writes, builds and tests the firmware for a board designed with
[hwde](https://github.com/ihsan-sa/hwde). The board's netlist decides every pin, and each target builds with warnings as
errors, runs host unit tests and boots in a simulator where one exists.

## Standing goals (the owner's words)

These are the owner's own direction for fwe, quoted as he said them. Only he adds, changes or drops one; a run reads
them and works toward them, and proposes the next step under Proposed goals below.

### FWE writes and debugs the firmware, and plans bring-up with NPIE

- **Said:** 2026-10-16 01:55 EDT, #iiks1-architect-autobox2-uxnu, slack:C0C8XQZ9JR0/1792130142.854639
- **His words:** "also the goal of FWE is to write FW based on HW,, advise HWDE on how to configure MCUs, write the FW and
  debug it, and make plans for NPIE to carry out the bringup where NPIE and FWE work together to find and fix issues
  during bringup"
- **What that means:** fwe starts from the board hwde designed and writes the firmware for it. It also works upstream
  of the board: it tells hwde how each MCU should be configured (pins, clocks, boot straps, debug access) while the
  board is still being drawn. Once the firmware builds, fwe debugs it, and it writes a bring-up plan that npie carries
  out on the real board. During bring-up the two work as a pair: npie reports what the board does, and fwe finds and
  fixes the firmware side of each issue.
- **Done when:** this is standing direction, so it is never closed. A board meets it when hwde has fwe's MCU advice
  before layout, its firmware builds and passes its tests, npie has a bring-up plan from fwe, and the issues found in
  bring-up are fixed on the firmware side.

## Proposed goals

Each goal says what to build, which files it touches and how to tell it is done. At most three are open at once, and
each keeps its status (open, done, failed or dropped) and the pull requests that moved it.

### Add the hi-fi USB-PD power limiter, self-test console and codec picks

- **Serves:** FWE writes and debugs the firmware, and plans bring-up with NPIE
- **Status:** open
- **What:** the hi-fi streamer boards are ESP32 boards running squeezelite-esp32, the target #10 added. This goal adds
  two ESP-IDF components of our own under `skill/templates/esp32/components/`, shaped like the `fwe_stub` example there:
  logic that needs no ESP-IDF in `core/`, tested on the host by `skill/templates/esp32/tests/host/`, the ESP-IDF glue
  beside it, and `-Werror`. It also adds the boards' parts to the codec table.
  1. `fwe_pd_limit`, a power limiter. It reads the PD contract from the CH224A USB-PD sink over I2C and the amplifier
     rail's current from an ADC, and caps the volume before the charger trips. It handles a 28 V EPR contract, a 20 V
     fallback, and plain 5 V USB, where the amplifier stays off.
  2. `fwe_selftest`, a console that implements the `npie-selftest/1` contract exactly. It answers `st rails`, `st pd`,
     `st tone <tap> <hz> <dBFS>` and `st net` with one `OK {json}` or `ERR <reason>` line each, the same over USB serial
     and over TCP. `st tone` plays through the DAC and reads it back through the PCM1863 loopback ADC and its mux.
     `skill/scripts/esp32_manifest.py` writes the `selftest` section of the manifest, and `skill/reference/manifest.md`
     documents it. The contract (`skill/reference/fwe-selftest.md`) and a fixture manifest are in
     [ihsan-sa/npie#19](https://github.com/ihsan-sa/npie/pull/19), which may not be on npie's main yet.
  3. The codec picks, in `skill/reference/esp32/codecs.json` and the DAC config that
     `skill/scripts/fwelib/squeezelite.py` writes. The Max board uses the TPA3255 amplifier (not the TPA3245) and the
     ES9018K2M DAC, and the Lite board may use the TAS5825P. An I2C sequence nobody has checked against the datasheet
     stays `"verified": false`, so pinmap reports it as a finding, as #10 does.
- **Fixtures:** the hi-fi boards' workspaces aren't published, so the tests build fixture netlists for them, as most
  tests here do.
- **Done when:** `make check` passes, including the new host tests and a pinmap, scaffold and manifest run on a fixture
  hi-fi netlist, and the pull request is merged.
- **Note:** this goal and the review fixes above both touch `squeezelite.py` and `codecs.json`, so do them one after the
  other.
- **Pull requests:** [#25](https://github.com/ihsan-sa/fwe/pull/25) starts item 1: `fwe_pd_limit`'s `core/` (CH224A
  register decode, the 28 V EPR, 20 V fallback and 5 V cases, the volume cap) and its host test. Left in item 1: the
  ESP-IDF glue (CH224A I2C read, rail ADC, applying the cap). The dispatch/59 branch maps the rail ADC for that glue:
  the ESP32 pinmap finds the amp rail's current sense, refuses an ADC2 pin (`isns_not_adc1`), reads its amp and
  shunt, and writes `RAIL_ISNS_ADC1_CH`, `_REF_V` and `_V_PER_A` to `board_pins.h` (#60). The dispatch/61 branch adds
  `fwe_pd_rail_ma()` to `core/`, which turns a calibrated ADC reading into rail mA with those two scales (a scale that
  isn't positive reads as over any contract, so the cap falls to its floor). [#30](https://github.com/ihsan-sa/fwe/pull/30) did
  item 3's table: TPA3255, ES9018K2M and TAS5825P in `codecs.json` (the two I2C parts `verified: false`, their
  addresses unchecked), with pinmap tests on a Max and a Lite fixture. Left in item 3: their init sequences, from the datasheets.
  [#56](https://github.com/ihsan-sa/fwe/pull/56) starts item 2: `fwe_selftest`'s `core/` (reads one `st rails|pd|tone|net` line, checks
  `st tone`'s tap, 20 to 20000 Hz and -60 to 0 dBFS, calls the board's handler and frames one `OK {json}` or
  `ERR <reason>` line) and its host test. The dispatch/57 branch adds the manifest's `selftest` section (the four
  commands, `st tone`'s ranges read from the component's header, the answer patterns, and `ready`, false while the
  component is only `core/`) and documents it in `manifest.md`. The dispatch/65 branch puts it in npie's ESP32
  bring-up plan: an `st:rails`, `st:pd` and `st:net` step once the section is `ready` (not `st tone`, whose taps the
  manifest doesn't name), and triage reads an `ERR <reason>` or no answer on one. The dispatch/67 branch names
  `st tone`'s taps: the PCM1863's mux inputs in `codecs.json` (unchecked, from memory), each one the netlist wires
  kept as `tone_taps` in `pinmap.json` with the named net it reads, and listed under `st tone` in the manifest.
  Left in item 2: an `st:tone` step in the plan, the handlers' JSON and the reason
  words checked against npie#19's contract, and the handlers and USB serial/TCP glue.

### Add the hi-fi sub crossover DSP and phone web app

- **Serves:** FWE writes and debugs the firmware, and plans bring-up with NPIE
- **Status:** open
- **What:** two more components of our own under `skill/templates/esp32/components/`, shaped like `fwe_stub`.
  1. `fwe_xover`, a sub crossover (an LR4 at about 80 Hz, for example) with per-sub level and delay, out on the second
     I2S port. The coefficients are computed in `core/`, and host tests check them.
  2. `fwe_webapp`, a phone web app for input select, volume, EQ and the sub settings, served by the ESP32 beside
     squeezelite's own web UI. A small HTTP/JSON API serves the app and, once the console above exists, the self-test.
     The settings persist in NVS, in the `fwe` namespace that `pinmap.py` already writes.
- **Upstream:** wiring either one into upstream (an init call, a DSP hook) is a patch this goal decides. Nothing is
  ever committed inside the `upstream/` clone.
- **Fixtures:** as above, the tests use fixture netlists for the hi-fi boards.
- **Done when:** `make check` passes, including host tests for the crossover coefficients and the API's request
  handling and a fixture build of both components, and the pull request is merged.
- **Pull requests:** [#32](https://github.com/ihsan-sa/fwe/pull/32) starts item 1: `fwe_xover`'s `core/` (LR4 low and high pass
  coefficients from 40 to 200 Hz, a per-sample filter step, each sub's level and delay) and its host test, which checks
  -6 dB at the crossover, -24.6 dB an octave out and a flat sum. [#36](https://github.com/ihsan-sa/fwe/pull/36) added each sub's delay line to
  `core/` (a fixed ring buffer, 20 ms at up to 96 kHz, cleared when the delay changes). Left in item 1: the second I2S
  port in the ESP-IDF glue. [#34](https://github.com/ihsan-sa/fwe/pull/34) starts item 2: `fwe_webapp`'s `core/` (the settings, GET and POST
  `/api/settings` with all-or-nothing range checks on a flat JSON body, keys that double as NVS keys) and its host
  test. The dispatch/63 branch adds the page, `fwe_webapp/page/index.html` (input, volume, EQ and the sub settings,
  each control posting its one key), and a test that checks its keys, inputs and ranges against the core's tables.
  Left in item 2: the HTTP server (serving the page, embedded, and the API), NVS and the self-test route in the
  ESP-IDF glue.

## Closed

What has landed so far, from the git history:

- `/fwe` imported from hwde as a standalone skill (#1).
- A golden netlist test, `make check` and the full manifest args (#2).
- `/fwe` builds and simulates FPGA gateware (#3).
- The 8-channel PWM bitstream for the picked ECP5 board (#4).
- The ECP5 EVN UART rework corrected, so R22 and R23 stay fitted (#5).
- The STM32G474 and its HRTIM, for the GaN boost board (#6).
- Both boost switches turn off at zero duty, and `setup --check` is fixed (#7).
- A `swo` role in the pin map for the SWO trace pin (#8).
- A required check job and a `make check` target (#9).
- An ESP32 (ESP-IDF) target for squeezelite-esp32 boards (#10).
- Fix the review findings from #10. All eight follow-ups in
  [issue #11](https://github.com/ihsan-sa/fwe/issues/11) landed with tests: C3/S3 parts refused (#14), the platform
  and `sdkconfig.fwe` hash kept in `fwe_build.json` (#16), build timeouts, flash-args and "IDF missing" tests (#18),
  uv checked before cloning ESP-IDF and the recipe's exit wording (#21), the AK4493S straps and SMUTE (#23). Its Done
  when (#11's boxes ticked and #11 closed) is the owner's to meet; no run's pull request closes #11.
- Write npie's bring-up plan from the manifest. **Status:** done. `bringup_plan.py` writes `firmware/bringup-plan.json`
  (`fwe-bringup-plan/1`) for MCU boards (#38) and ESP32 boards (#40), and the `bringup` and `esp32-bringup` router
  verbs (with `full-run`'s last step) run the manifest then the plan (the dispatch/41 branch). Its check,
  `python -m pytest -q tests/test_bringup_plan.py -k "esp32 or router"`, passes in `make check`. Left for later:
  `fwe_selftest`'s steps, once its manifest section exists, and a `send` for the NVS readback once upstream's
  console command is pinned.
- Advise hwde on each MCU's configuration before layout. **Status:** done. `mcu_advice.py` writes
  `firmware/mcu-advice.json` (`fwe-mcu-advice/1`) from the draft netlist: STM32 debug access, NRST and BOOT0
  ([#44](https://github.com/ihsan-sa/fwe/pull/44)); classic ESP32 straps, EN and UART0
  ([#46](https://github.com/ihsan-sa/fwe/pull/46)); clocks (an HSE crystal when the board has CAN, a bare ESP32's
  40 MHz crystal, load caps) and the `advise` router verb for STM32 and ESP32 boards, with its recipe (the dispatch/47
  branch). Its check, `python -m pytest -q tests/test_mcu_advice.py -k router`, passes in `make check`.
- Answer npie's bring-up failure reports. **Status:** done. `bringup_triage.py` reads npie's failed-step report
  (`fwe-bringup-report/1`) against the plan and writes `firmware/bringup-triage.json` (`fwe-bringup-triage/1`):
  console-line findings first, then the step's `fwe_suspects`, each `firmware`, `hardware` or `bench`
  ([#50](https://github.com/ihsan-sa/fwe/pull/50)); the `triage` router verb for STM32 and ESP32 boards, its recipe
  and both schemas ([#52](https://github.com/ihsan-sa/fwe/pull/52)); each triage kept as an issue in
  `firmware/bringup-log.json` (`fwe-bringup-log/1`), with `--fix` and `--open` (the dispatch/53 branch). Its check,
  `python -m pytest -q tests/test_bringup_triage.py -k router`, passes in `make check`.
