# build

`fw_build.py --workspace <board> [--stage <name>] [--clean]`: pin-map drift
check, CMake configure, build. Warnings are errors (the template's flags);
vendor sources are the only files compiled without them.

- exit 1 `step: pinmap` -> the board changed; run the pinmap recipe.
- exit 1 `step: compile` -> read `log_tail`, fix the source. Never drop
  `-Werror` or add a `-Wno-` to pass; fix the code or explain in a comment
  why a specific cast is right.
- exit 2 -> the toolchain is missing; run setup.
- Record `size` in the journal; flash is 128 KB on the G431CB.
