# full-run

The whole path for one board, as separate verbs in order: setup, scaffold
(then set `config/fw_config.h` from requirements), stage bringup, build,
test, sim, manifest (`--sim renode` when the sim passed). Journal the size, the test count and what is unverified after each
step. The firmware lands in the boards repo through its own PR, never in
this repo.

Report plainly which rung each claim reached: pin map, build, host tests,
simulation, hardware (hardware is /npie's, never /fwe's).
