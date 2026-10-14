# esp32-build

`esp32_build.py --workspace <board>` builds the firmware the way upstream's CI does
(`build-scripts/<PLATFORM>-sdkconfig.defaults`, `idf.py build -DDEPTH=16`) in the pinned
ESP-IDF, with our components linked in. The sdkconfig and every output stay in
`firmware/build/`; upstream's tracked `sdkconfig` is never touched.

- PLATFORM is the `# PLATFORM=` line of `firmware/sdkconfig.fwe` (default I2S-4MFlash,
  upstream's generic WROVER build); the rest of that file applies after the platform's
  defaults. `--platform` overrides it for one run.
- Our components must build with `-Werror`: the step `werror` fails when any `fwe_*`
  source in `compile_commands.json` was compiled without it. Upstream keeps its flags.
- The NVS image: `gen/nvs_config.csv` through ESP-IDF's `nvs_partition_gen.py`, sized as
  upstream's `settings` partition. `flash` in the JSON lists every image with its offset,
  the NVS one last, for `esptool.py write_flash`.
- Exit 1 with step `pinmap` is drift: rerun `pinmap.py` and review the diff. Step
  `upstream`: the clone is not at the lock's commit (`fw_scaffold.py --update`).
  Exit 2 at step `idf`: run `esp32-setup`.
- A clean build takes several minutes; the log is `firmware/build/fwe_build.log`.
