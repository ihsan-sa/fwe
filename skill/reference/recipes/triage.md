# triage

`bringup_triage.py --workspace <board>` reads /npie's report of the bring-up
step that failed (`firmware/bringup-report.json`, `fwe-bringup-report/1`) against
`firmware/bringup-plan.json` and writes `firmware/bringup-triage.json`
(`fwe-bringup-triage/1`, `reference/manifest.md`, "The failure report and its
triage"). It serves STM32 and ESP32 boards.

- Read `findings` in order: the ones with `evidence` come from the console
  lines, the rest are the step's `fwe_suspects`.
- `side: firmware` -> fix it here, rebuild, re-run the manifest and plan, and
  have /npie start again from `rerun_from`.
- `side: hardware` -> a finding for hwde; never edit the board's KiCad files
  yourself (SKILL.md rule 1). `side: bench` -> /npie's setup, not the board.
- exit 1 -> no plan: run the `bringup` or `esp32-bringup` verb first.
- exit 2 -> a report this can't read (another schema or board, or a step the
  plan doesn't have); ask /npie for the report again.
- A triage names where to look, not the cause; confirm it before a fix.
- Each triage is an issue in `firmware/bringup-log.json` (its `n` is in the
  output). Once a fix answers it, record it with
  `bringup_triage.py --workspace <board> --fix <n> "<what changed, version>"`;
  `--open` lists the board's bring-up issues still open.
