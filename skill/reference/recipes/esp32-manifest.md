# esp32-manifest

`esp32_manifest.py --workspace <board>` writes `firmware/fwe-manifest.json` in the
`fwe-esp32-manifest/1` schema (`reference/manifest.md`, "ESP32 boards") from the pin map
and the last `esp32_build.py` run; `--check` writes nothing and exits 1 when it is stale.
Run `esp32-build` and `esp32-test` first: `verified.build` and `verified.host_tests` are
read from their results, and an image whose sha256 no longer matches the build makes
`verified.build` false rather than being trusted.
