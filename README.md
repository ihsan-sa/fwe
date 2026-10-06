# fwe — a firmware engineer skill for Claude Code

`/fwe` is a [Claude Code](https://claude.com/claude-code) skill that writes,
builds and tests the firmware for a board designed with
[hwde](https://github.com/ihsan-sa/hwde). You give it a task in your own
words and a board, and one router (`task_router.py`) picks the step: set up
the toolchain, derive the pin map from the board's netlist, scaffold a
firmware project, write a stage (bring-up, six-step, FOC), build with warnings
as errors, run the host unit tests, boot it in a simulator, or review it.
The board's netlist decides every pin, so nobody types a pin number. STM32G4
is the first MCU family it supports.

```
/fwe build it with warnings as errors bldc-motor-driver
```

## Install

The skill is the `skill/` directory. Link it (or copy it) into your Claude
Code skills directory under the name `fwe`:

```sh
git clone https://github.com/ihsan-sa/fwe.git
ln -s "$PWD/fwe/skill" ~/.claude/skills/fwe
```

To use it in one project only, link it into that project's
`.claude/skills/fwe` instead.

## Boards

`/fwe` works on hwde board workspaces. It finds them under
`HWDE_BOARDS_ROOT`, which defaults to `~/dev/boards`. A board is named by a
path or by its directory name under that root, and a bare name such as
`bldc-motor-driver` also finds a numbered workspace like
`PCB-0018-A_bldc-motor-driver`. The firmware lives in the board's workspace
as `firmware/`, next to the `kicad/` export it reads, and `/fwe` never edits
the board's KiCad files.

## Toolchain

The scripts need Python 3.10 or later and nothing outside its standard
library. The host unit tests need a host C compiler (`gcc`, `clang` or `$CC`).

The cross toolchain is pinned in `skill/reference/toolchain.lock.json`, and
`/fwe setup` (or `python3 skill/scripts/fwe_setup.py`) installs it into
`~/.local/fwe-tools`, or `FWE_TOOLS_DIR` when that is set. It needs no root.
Each download is checked against its pinned sha256, and the pinned builds
are the Linux x64 ones. The pinned set is:

- xPack arm-none-eabi-gcc 15.2.1, CMake 3.31 and Ninja 1.13
- xPack QEMU Arm 9.2 and Renode 1.17, for the simulator smoke test
- CMSIS Core 5.9.0 and the STM32G4 CMSIS device headers v1.2.6

## FPGA gateware

`/fwe` also writes FPGA gateware, through the `fpga-*` verbs. The first
design drives eight PWM outputs at 13.56 MHz with each channel's phase set
in steps of about 1 ns, through the FPGA's output serialiser, and a UART
register protocol sets phase and duty. The core and its testbench don't
depend on the board: the serialiser primitive and the pins sit in
`vendor/<family>/` and `gateware.json`. `skill/reference/fpga.md` has the
protocol and the manifest /npie reads.

Simulation and synthesis use chip-flow's
`bin/eda` toolchain (Icarus, Verilator, Yosys, cocotb), the same one `/vde`
uses, found at `CHIP_FLOW_HOME` (default `~/.claude/skills/chip-flow`).
Place and route needs `nextpnr-ecp5` and `ecppack`: `fpga_setup.py --install`
unpacks a pinned OSS CAD Suite under `~/.local/share/fwe/`, user space only.

## Tests

```sh
make venv     # once: .venv with pytest
make check    # the whole suite; the gate a change must pass
```

`tests/golden/netlist/` holds a copy of hwde's golden netlist export and what
hwde's reader makes of it, so a test holds fwe's copied reader to hwde's.

Most tests build their own small netlist. The few that need a real board
skip with the reason when the boards repo isn't at `HWDE_BOARDS_ROOT`, and
the cross-build and simulator tests skip when the pinned toolchain isn't
installed. The FPGA bench and synthesis tests skip when chip-flow's `eda`
isn't there.

## Layout

- `skill/SKILL.md` is the playbook Claude reads, and `skill/scripts/` holds
  the router and one script per step.
- `skill/reference/` has the design notes, one recipe per step, the MCU pin
  tables and the toolchain lock.
- `skill/templates/` is the firmware project a scaffold starts from.
- `tests/` holds the pytest suite.

## Credit

`/fwe` started inside hwde. Its netlist reader returns the same shape as
hwde's `simlib.parse_netlist`, and the boards root follows hwde's
`env.boards_root`.

## License

MIT, see [LICENSE](LICENSE).
