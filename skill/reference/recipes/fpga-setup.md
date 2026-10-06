# fpga-setup

`fpga_setup.py` checks. Simulation and synthesis run on chip-flow's
`bin/eda` (the tree /vde uses), so a missing sim or synth tool (exit 2) means
chip-flow's toolchain is not unpacked: that is chip-flow's setup, not /fwe's.
Exit 1 means only place and route is missing (`nextpnr-ecp5`, `ecppack`):
sim, lint and synthesis still work. `fpga_setup.py --install` then fetches
the pinned OSS CAD Suite release, checks its SHA256 and unpacks it into
`~/.local/share/fwe/oss-cad-suite` (`FWE_FPGA_TOOLS`), user space only; the
build finds the tools there. Moving the pin to a newer release is a change
to `RELEASE` and `SHA256` together, with the asset digest GitHub publishes.
