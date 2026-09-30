# setup

Install or check the pinned firmware toolchain: `fwe_setup.py` (all), `--check`
(report only), `--only <name>`. Everything goes under `~/.local/fwe-tools`
from `reference/toolchain.lock.json`; a sha256 mismatch stops the install.

- Never reach for apt, a container or sudo. If a tool cannot be had in user
  space, stop and ask the owner.
- Changing a pin: edit the lock (url, sha256 from the vendor's .sha file,
  version), run `fwe_setup.py --only <name>`, rebuild a board, and add a
  LEARNINGS `[fwe][toolchain]` line saying why.
