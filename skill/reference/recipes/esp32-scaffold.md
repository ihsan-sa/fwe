# esp32-scaffold

`fw_scaffold.py --workspace <board>` on a board whose netlist has an ESP32 module.
It runs the pin map, copies `templates/esp32/` into `firmware/` (never over a file that
is there), clones upstream squeezelite-esp32 into `firmware/upstream/` at the commit
`reference/toolchain.lock.json` pins under `upstreams`, with its submodules, and links
each `firmware/components/fwe_*` into `upstream/components/`. The links are listed in
upstream's `.git/info/exclude`, so `git -C firmware/upstream status` stays clean, apart from the file modes
upstream's own build sets on cspot's nanopb generator.

- Never fork upstream, add a remote, or push from `firmware/upstream`: a fork is the
  owner's call. A change upstream needs is a patch the row that needs it proposes.
- Moving upstream: change the lock's commit (with the ESP-IDF version its CI uses, see
  `esp32-setup.md`), then `fw_scaffold.py --workspace <board> --update`. Without
  `--update` a clone at another commit is reported (`upstream_moved`, exit 1), not moved.
- `--no-fetch` copies the template only (offline, or to look at it).
- New features are new `components/fwe_<name>/` shaped like `fwe_stub` (read its README):
  logic in `core/`, ESP-IDF glue beside it, `-Wall -Wextra -Werror` in its CMakeLists.txt,
  a host test in `tests/host/`. Rerun the scaffold or the build to link it.
