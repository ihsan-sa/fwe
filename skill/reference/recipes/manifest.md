# manifest

`fw_manifest.py --workspace <board> [--sim renode]` writes
`firmware/fwe-manifest.json` after a build; `--check` says whether the file on
disk still matches the firmware (exit 1 lists the `stale` keys). The contract
is `reference/manifest.md`.

- Run it after every build that is meant for /npie, and commit the manifest
  with the firmware it describes: its sha256s pin the exact binary.
- Everything in it is derived. To change a limit, edit `config/fw_config.h`;
  to add a command, add it to the dispatch in `src/console.c` and declare it on
  that line: `/* fwe-cmd args="<duty 0..1> <fwd|rev> | stop" safe=no */`.
  Never hand-edit the manifest; --check rejects it.
- exit 2 `command(s) ... have no declared args` -> a console command is neither
  declared nor in the script's `KNOWN` table; declare it on its dispatch line.
- exit 1 `no firmware/build/...` -> run the build verb first.
- `verified.sim` stays null unless a simulator smoke test passed; never
  claim one you did not run.
