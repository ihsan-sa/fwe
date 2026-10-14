# Firmware: squeezelite-esp32 plus our components

- `upstream/` is squeezelite-esp32 at the commit /fwe's toolchain lock pins, cloned with its
  submodules by `fw_scaffold.py`. It is a plain clone with no remote of ours: never commit in it.
  Moving to a newer upstream is a lock change, then `fw_scaffold.py --workspace <ws> --update`.
- `components/fwe_*` is our code, one ESP-IDF component each. The scaffold links each into
  `upstream/components/` and lists the links in upstream's `.git/info/exclude`, so upstream's
  tree stays clean and a rebase never meets our files. (Upstream's own build chmods
  cspot's nanopb generator, so `git status` there shows those mode changes after a build.)
- `gen/` is written by `pinmap.py` from the netlist: `board_pins.h` and `nvs_config.csv`
  (squeezelite's `config` namespace plus our `fwe` one). Never edit it by hand.
- `sdkconfig.fwe` is applied on top of upstream's platform defaults (`PLATFORM` in it).
- `tests/host/` holds host unit tests for the pure logic in `components/*/core/`.

Our components build with `-Wall -Wextra -Werror`; upstream keeps its own flags.
