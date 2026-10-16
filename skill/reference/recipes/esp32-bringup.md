# esp32-bringup

`esp32_manifest.py --workspace <board>` then `bringup_plan.py --workspace <board>`
writes `firmware/bringup-plan.json` (`fwe-bringup-plan/1`, `reference/manifest.md`,
"The bring-up plan") for an ESP32 board: power, the ROM-bootloader flash with
its boot strap, the ROM's reset line on upstream's console, one `nvs:*` step per
setting read back against the manifest, then its test hooks if any.

- Run `esp32-build` and `esp32-test` first, so the manifest's `verified` says
  what they found; the plan copies it for /npie.
- The plan is derived from the manifest; never hand-edit it.
- exit 1 `no ... fwe-manifest.json` -> the manifest step failed; fix that first.
- When /npie reports a failed step, save its report as `firmware/bringup-report.json`
  and run the `triage` verb (`recipes/triage.md`).
