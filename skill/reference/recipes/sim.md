# sim

`fw_sim.py --workspace <board> [--send <line> ...]` boots `build/fw.elf` in
Renode on the one `firmware/sim/*.repl` (`g431.repl` for the G431 motor
boards, `g474.repl` for the G474 HRTIM boost) and sends console lines (default
`version`, `status`) on the repl's first UART (usart1 or usart2). Pass = the
banner, the boot EVT and one reply per line.

What it proves: the ELF boots, the clock code finishes, the vector table and
console UART interrupt work, the console parses and answers. What it does not:
RCC and the ADC are stubs (every conversion reads mid-scale), and TIM1, COMP,
DAC, GPIO and the watchdog are unmodelled, so PWM, current sense, fault
thresholds and the gate driver are untested. Say so whenever you report a pass.

G474: the repl also has `hrtim.py`, a read-back HRTIM stub with a sim-only
fault-inject register, so the run adds an HRTIM step. It sends `arm`, reads
Timer A PER, CMP1, DT and the output enables, asserts the OVP comparator's
FLTn, reads them again and sends `status`. Pass also needs PER at the board's
fsw (+-1%), both dead times within one DT step of `DEADTIME_NS`, the outputs
off after the fault and `status` showing `ovp_hw` latched (JSON `hrtim`).
That proves the firmware programs the period, dead time and fault enables and
latches the fault flag. It does not prove PWM edges, the DLL, the comparator
thresholds or the ADC trigger: no ADC interrupt fires in the sim, so the
control sample goes stale and `arm` is refused (`ERR hw`), and the outputs
were never on before the fault.

- Pass -> write the manifest with `--sim renode`.
- A new stage that polls another peripheral's ready flag hangs or crawls here
  (Renode logs every unmapped read): stub it in `sim/` like `adc.py`, never by
  adding a firmware `#ifdef SIM`.
- exit 2 -> no build, not exactly one `*.repl` in `sim/`, or Renode missing
  (run setup).
