# The firmware manifest (/fwe -> /npie)

/fwe writes `firmware/fwe-manifest.json` next to every build; /npie reads it
to flash the board and drive the firmware. It is the whole interface: /npie
never reads firmware sources, and /fwe never assumes a bench.
`scripts/fw_manifest.py` derives it and `--check` says whether one is stale.

Where each part comes from: connectors and pins from the board's netlist (the
J* part on the MCU's SWD and UART nets, through one series resistor), the
command list from the dispatch in `src/console.c` (one entry per command
the firmware answers, so a later stage's `spin` appears when its console
handles it; `reply_fields` are the top-level keys of its `OK` object, read from
the handler; `args` and `safe` come from a `/* fwe-cmd args="..." safe=yes|no */`
comment on the command's dispatch line, which a stage writes for each command it
adds, else from the script's table of the bringup commands; a command in
neither is refused, so every command carries its arguments), `safety` from
`config/fw_config.h` (`pwm_hz` is `PWM_FREQ_HZ`), `stage`/`version` from the build's CMake cache, and the
sha256s from `build/`. `verified` records evidence, not a derivation:
`host_tests` is whether fw_test.py passed when the manifest was written, `sim`
the simulator a smoke test passed in (null when none ran), and `hardware` is
always false because /fwe never touches a bench.
The example below lists three of the eleven bring-up commands.

```json
{
  "schema": "fwe-manifest/1",
  "board": "PCB-0018-A",
  "mcu": {"part": "STM32G431CBT6", "core": "cortex-m4", "flash_base": "0x08000000"},
  "stage": "bringup",
  "version": "0.1.0+g<sha>",
  "artifact": {"elf": "build/fw.elf", "bin": "build/fw.bin", "hex": "build/fw.hex",
               "sha256": {"elf": "...", "bin": "...", "hex": "..."}},
  "flash": {
    "interface": "swd", "connector": "J601",   // + "swo_pin": "PB3" when the board routes SWO
    "commands": {
      "probe-rs": ["probe-rs", "download", "--chip", "STM32G431CBTx", "{elf}"],
      "openocd": ["openocd", "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                  "-c", "program {elf} verify reset exit"]
    }
  },
  "uart": {"connector": "J701", "tx_pin": "3", "rx_pin": "4", "baud": 115200,
           "format": "8N1", "levels": "3V3", "banner_regex": "^fwe PCB-0018-A "},
  "commands": [
    {"name": "status", "args": "", "reply": "OK {json} | ERR <code> <text>",
     "reply_fields": ["armed", "faults", "active", "vbus_v", "i_a", "duty",
                      "hw_trip", "uptime_ms"], "safe": true},
    {"name": "arm", "args": "", "reply": "...", "reply_fields": ["armed", "duty"],
     "safe": false},
    {"name": "duty", "args": "<a> <b> <c>", "reply": "...",
     "reply_fields": ["duty", "max_duty"], "safe": false}
  ],
  "test_hooks": [{"name": "selftest", "send": "selftest", "expect": "^OK ",
                  "timeout_s": 5, "needs": ["+3V3"]}],
  "safety": {"pwm_at_reset": "off", "fault_clear": "clear", "i_trip_a": 20.0,
             "i_limit_a": 15.0, "vbus_ov_v": 30.0, "vbus_uv_v": 9.0, "max_duty": 0.95,
             "pwm_hz": 20000},
  "verified": {"build": true, "host_tests": true, "sim": null, "hardware": false}
}
```

## UART protocol (line-based ASCII)

- One command per line, `\n`-terminated, lowercase words separated by spaces.
- Every command gets exactly one reply line: `OK <json>` or `ERR <code> <text>`.
  The JSON is a single object on one line so a script can parse it.
- Asynchronous events are lines starting `EVT <json>` (a fault trip, a
  button press); a driver must accept them between a command and its reply.
- Boot prints one banner line matching `banner_regex`, then `EVT {"boot":...}`
  carrying the reset cause.
- Commands a motor board firmware implements at the bringup stage:
  `version`, `status`, `selftest`, `adc` (raw + scaled channels),
  `offsets` (re-run current-sense offset calibration, bridge off),
  `led <status|fault> <on|off|auto>`, `arm` (MOE on, 0 duty), `disarm`,
  `duty <a> <b> <c>` (0..1, refused unless armed and capped by `max_duty`),
  `clear` (clear a latched fault), `reset`.
  Each is listed in `commands` with `safe: false` when it can energise the
  bridge, so /npie can require its own human confirmation step first.

`safety.i_trip_a` is the hardware comparator trip into the timer's break
input, and it sees positive phase current only. Negative over-current is
caught in software against `i_limit_a` on |i|, so a
/npie step that tests the trip must drive current in the positive direction.

## The HRTIM boost (stm32g474-boost template)

A board whose pin map has an `hrtim_` role (PCB-0026-A) gets the boost
template, and its manifest differs in three places. `stage` is `boost`.
`safety` keeps `vbus_uv_v`/`vbus_ov_v` as the input supply's limits, as on
the motor boards, and adds `vout_target_v`, `vout_ov_v` and `dead_time_ns`;
`max_duty` is the boost's `D_MAX`. And two keys are added:

```json
"pwm": {"timer": "HRTIM Timer A", "freq_hz": 1000000, "dead_time_ns": 10,
        "max_duty": 0.82, "safe_state": "both outputs low",
        "outputs": [{"pin": "PA8", "net": "PWM_LO", "role": "hrtim_lo"},
                    {"pin": "PA9", "net": "PWM_HI", "role": "hrtim_hi"}]},
"trips": [{"name": "ovp", "kind": "hardware", "sense_net": "VOUT_SNS", "pin": "PA0",
           "comparator": "COMP3", "fault_input": "FLT5", "threshold": 55.0, "unit": "V",
           "outputs": "inactive", "latched": true, "clear": "clear",
           "evt_regex": "^EVT {\"trip\":{\"new\":\\[[^]]*\"ovp_hw\""}]
```

`trips` has one entry per comparator -> HRTIM fault route in the pin map.
The comparator forces both outputs inactive with no firmware in the path,
the firmware latches the fault, reports it once as an `EVT` matching
`evt_regex`, shows it in `status`, and `clear` releases it only once the
comparator has fallen. `threshold` is the trip level at the sense net's
source (output volts, inductor amps), from `config/fw_config.h`.
`commands`: `arm` starts the soft start into the voltage loop, and
`duty <d>` drives an open-loop duty for the bench (both `safe: false`).
`duty 0` turns both outputs off rather than holding the high side on, and
they come back on once a real pulse has reached the timer's compare.

## Test hooks

`test_hooks` are what /npie runs unattended after flashing: a `send` line, a
regex `expect` on the reply, a timeout, and the rails the hook needs powered
(`needs`), so /npie can order them after its power-up steps. A hook never
energises the bridge; anything that does is a `commands` entry with
`safe: false` and belongs in a human-confirmed /npie step.

## The bring-up plan

`scripts/bringup_plan.py` turns the manifest into `firmware/bringup-plan.json`
(schema `fwe-bringup-plan/1`), the steps /npie carries out on the real board, in
order: `power` (a human brings up the rails the hooks need, current-limited),
`flash`, `boot` (the banner, then the `EVT` boot line), one `hook:<name>` per
test hook (unattended), then one `cmd:<name>` per `safe: false` command, each
sent only after a human confirms it (`kind: confirm`, with `safety` as
`limits`). /npie stops at the first step that fails and reports the step id,
the console lines it saw and the supply current (`on_fail.report`); each step's
`fwe_suspects` is where /fwe looks first for the firmware side of it.

An ESP32 manifest (`fwe-esp32-manifest/1`, below) has no fwe console, so its
plan is `power`, `flash` (esptool over the ROM bootloader, with the manifest's
`boot_strap` and each image's sha256), `boot` (the ROM's `rst:` line, then
ESP-IDF's first `I (…)` log line, on upstream's console), then one
`nvs:<namespace>.<key>` step per setting in `nvs.namespaces`, read back over
upstream's console and compared verbatim with `expect`, then its test hooks
as above. Any other schema is refused.

### The failure report and its triage

/npie's report of the step that failed is `fwe-bringup-report/1`, saved as
`firmware/bringup-report.json`: `board` (the plan's), `step` (a plan step id),
`lines` (the console lines it saw, oldest first) and `current_a` (the supply
current, or null). `scripts/bringup_triage.py` reads it against the plan and
writes `firmware/bringup-triage.json` (`fwe-bringup-triage/1`): `board`,
`stage`, `version`, `step`, `current_a`, `findings` (each a `side`, `firmware`,
`hardware` (a finding for hwde) or `bench`; a `suspect`; and the console line
that points there as `evidence`, or null for one of the step's `fwe_suspects`),
`side` (the first finding's) and `rerun_from`, the step /npie starts again
from once the fix lands.

Each triage is kept as an issue in `firmware/bringup-log.json`
(`fwe-bringup-log/1`): `board` and `issues`, each with `n` (from 1), `step`,
`version`, `side`, `suspect` and `evidence` (the first finding's),
`current_a` and `fix`, the fix that answered it, or null while it is open.
The same triage read again is not logged twice. `bringup_triage.py --fix N
TEXT` records a fix and `--open` lists the issues still open.

## Versioning

`schema` changes its number on any breaking change. Additive keys are
allowed within a version, and a reader ignores keys it does not know.

## ESP32 boards (squeezelite-esp32)

An ESP32 board's firmware is upstream squeezelite-esp32 with our components, so its
manifest has its own schema, `fwe-esp32-manifest/1`, written by `esp32_manifest.py`.
/npie flashes it over the ROM bootloader and talks to it on the network, so there is no
`fwe` command protocol: `commands` and `test_hooks` are empty until a component of ours
adds some, and the console is upstream's own.

```json
{
  "schema": "fwe-esp32-manifest/1",
  "board": "PCB-0029-A",
  "mcu": {"part": "ESP32-WROVER-E-N8R8", "core": "xtensa-lx6", "chip": "esp32",
          "flash_mb": 8, "psram_mb": 8},
  "firmware": {"base": "squeezelite-esp32", "upstream_commit": "af2e157f…",
               "pinned_commit": "af2e157f…", "esp_idf": "v4.4.8", "platform": "I2S-4MFlash"},
  "images": [{"name": "bootloader", "offset": "0x1000", "file": "build/bootloader/bootloader.bin",
              "sha256": "…"},
             {"name": "nvs_config", "offset": "0x…", "file": "build/nvs_config.bin", "sha256": "…"}],
  "flash": {"interface": "uart-rom-bootloader", "tx_gpio": 1, "rx_gpio": 3, "baud": 460800,
            "boot_strap": "GPIO0 low at reset",
            "command": ["esptool.py", "--chip", "esp32", "-b", "460800", "write_flash", "-z",
                        "--flash_mode", "dio", "--flash_freq", "80m", "--flash_size", "4MB",
                        "0x1000", "build/bootloader/bootloader.bin", "…"]},
  "console": {"tx_gpio": 1, "rx_gpio": 3, "baud": 115200, "format": "8N1", "levels": "3V3",
              "commands": "upstream squeezelite-esp32's own console"},
  "nvs": {"csv": "gen/nvs_config.csv", "partition": "settings",
          "namespaces": {"config": {"dac_config": "model=I2S,bck=33,ws=26,do=25"}, "fwe": {}}},
  "commands": [],
  "test_hooks": [],
  "verified": {"build": true, "host_tests": true, "hardware": false}
}
```

`images` is every image `idf.py` flashes, in its order, with the NVS settings image last
at the offset of upstream's `settings` partition; `file` is relative to `firmware/`.
`flash.command` is run from `firmware/` and carries the flash mode, frequency and size
`idf.py flash` would pass. `verified.build` is false once `gen/nvs_config.csv` or an image
differs from what the build made, and `verified.host_tests` once our components or host
tests have changed since they passed. `flash_mb`/`psram_mb` come from the module's
ordering code and are null when it has none. `firmware.upstream_commit` is what was
built; it differs from `pinned_commit` only if the build ran before a lock change was
taken up. `nvs.namespaces` is what the pin map wrote, so /npie can compare it with what
the board reports.
