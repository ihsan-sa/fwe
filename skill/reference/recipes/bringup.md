# bringup

`fw_manifest.py --workspace <board>` then `bringup_plan.py --workspace <board>`
writes `firmware/bringup-plan.json` (`fwe-bringup-plan/1`, `reference/manifest.md`,
"The bring-up plan"), the steps /npie carries out on the real board in order:
power, flash, boot, each test hook, then each `safe: false` command behind a
human's confirmation.

- Run it whenever a board goes to /npie, after the build, test and manifest
  verbs, and commit the plan with the manifest it came from.
- The plan is derived. To change a step, change the manifest's source (the
  console's `fwe-cmd` lines, `config/fw_config.h`); never hand-edit the plan.
- exit 1 `no ... fwe-manifest.json` -> the manifest step failed; fix that first.
- exit 2 -> a manifest this can't plan (another schema, or a key missing).
- When /npie reports a failed step, start from that step's `fwe_suspects`.
