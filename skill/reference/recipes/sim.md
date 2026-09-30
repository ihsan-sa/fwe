# sim

`fw_sim.py --workspace <board> [--send <line> ...]` boots `build/fw.elf` in
Renode on `firmware/sim/g431.repl` and sends console lines (default `version`,
`status`). Pass = the banner, the boot EVT and one reply per line.

What it proves: the ELF boots, the clock code finishes, the vector table and
USART1 interrupt work, the console parses and answers. What it does not:
RCC and the ADC are stubs (every conversion reads mid-scale), and TIM1, COMP,
DAC, GPIO and the watchdog are unmodelled, so PWM, current sense, fault
thresholds and the gate driver are untested. Say so whenever you report a pass.

- Pass -> write the manifest with `--sim renode`.
- A new stage that polls another peripheral's ready flag hangs or crawls here
  (Renode logs every unmapped read): stub it in `sim/` like `adc.py`, never by
  adding a firmware `#ifdef SIM`.
- exit 2 -> no build, no `sim/`, or Renode missing (run setup).
