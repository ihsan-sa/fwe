# scaffold

`fw_scaffold.py --workspace <board>` copies `templates/<family>/` into the
board's `firmware/` and runs the pin map. Existing files are kept, never
overwritten, so re-running it only adds what is missing.

Then set `config/fw_config.h` from the board's `requirements.md`: bus
over/under-voltage, hardware trip and software current limits, PWM frequency,
dead time. Every value gets a comment naming the requirement line it comes
from. Build and test before anything else.
