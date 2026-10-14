# esp32-setup

Install or check ESP-IDF for the esp32 target: `fwe_setup.py --only esp-idf`
(`--check` to report only). The lock's `frameworks` entry pins the version
upstream squeezelite-esp32 builds with, read from its Dockerfile and the CI
image `.github/workflows/Platform_build.yml` uses, never from memory. It
installs into `~/.local/fwe-tools/esp-idf-<version>/`, with IDF's compilers
and python env under `~/.local/fwe-tools/espressif/` (about 2 GB, 5-10
minutes). A plain `fwe_setup.py` skips it, so STM32 work never pays for it.

- IDF runs on the python the lock names (upstream's image uses 3.8), from
  `uv`. IDF 4.4 cannot make its env on uv's python itself, so setup seeds
  the venv where IDF expects it and lets IDF fill it.
- Moving the pin: only when upstream moves. Read the new tag and commit from
  upstream's Dockerfile at the `upstreams` commit you are moving to, check
  `git ls-remote <repo> refs/tags/<tag>^{}` gives that commit, edit both
  entries, re-run setup and rebuild a board. Add a LEARNINGS
  `[fwe][toolchain]` line saying why.
