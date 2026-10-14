# fwe goals

`/fwe` is a Claude Code skill that writes, builds and tests the firmware for a board designed with
[hwde](https://github.com/ihsan-sa/hwde). The board's netlist decides every pin, and each target builds with warnings as
errors, runs host unit tests and boots in a simulator where one exists.

## Proposed goals

Each goal says what to build, which files it touches and how to tell it is done. At most three are open at once, and
each keeps its status (open, done, failed or dropped) and the pull requests that moved it.

### Fix the review findings from #10

- **Status:** open
- **What:** the review of the ESP32 target ([#10](https://github.com/ihsan-sa/fwe/pull/10)) left eight follow-ups,
  listed in [issue #11](https://github.com/ihsan-sa/fwe/issues/11).
  1. ESP32-C3 and ESP32-S3 parts take the classic ESP32 path. Detection in `skill/scripts/pinmap.py` and
     `skill/scripts/fw_scaffold.py` should accept only classic ESP32 modules, and a C3 or S3 should get a clear error
     instead of classic pin tables and an xtensa manifest from `skill/scripts/esp32_manifest.py`.
  2. A later `--platform` or `sdkconfig.fwe` change is silently ignored by `skill/scripts/esp32_build.py`. Store the
     platform and a hash of `sdkconfig.fwe` in `fwe_build.json`, and drop `build/sdkconfig` when either changes.
  3. Six smaller ones: the AK4493S address strap and mute polarity in `skill/scripts/fwelib/squeezelite.py`, an ESP-IDF
     re-clone in `skill/scripts/fwe_setup.py` on hosts without uv, an uncaught build timeout in `esp32_build.py`, a
     wording fix in `skill/reference/recipes/esp32-build.md`, and offline tests for the flash-args parsing and the
     "IDF missing" step.
- **Done when:** every checkbox in #11 is ticked, each fix has a test where one fits, `make check` passes, and the pull
  request that closes #11 is merged.
- **Pull requests:** [#14](https://github.com/ihsan-sa/fwe/pull/14) did item 1 (C3/S3 parts are refused by pinmap,
  scaffold and manifest); [#16](https://github.com/ihsan-sa/fwe/pull/16) did item 2 (`fwe_build.json` keeps the
  platform and the `sdkconfig.fwe` hash, and a change drops `build/sdkconfig`); [#18](https://github.com/ihsan-sa/fwe/pull/18)
  did three of item 3's six (a build timeout is a failed `build` step, not a traceback; offline tests for the
  flash-args parsing and the "IDF missing" step); the dispatch/20 branch does two more (setup checks uv before
  cloning ESP-IDF and keeps a clone already at the pinned commit; the esp32-build recipe's exit codes match the
  script). Left: the AK4493S strap and mute.

### Add the hi-fi USB-PD power limiter, self-test console and codec picks

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
- **Pull requests:** none yet.

### Add the hi-fi sub crossover DSP and phone web app

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
- **Pull requests:** none yet.

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
