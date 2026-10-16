# fwe_stub: where our components go

Each feature is its own component beside this one, shaped like it: logic that needs no
ESP-IDF in `core/` (built and tested on the host by `tests/host/`), the ESP-IDF glue
beside it, `-Werror` in its CMakeLists.txt. The planned ones, each a follow-up row:

- `fwe_pd_limit`: the USB-PD power limiter, caps amplifier gain to the negotiated contract
  (its `core/`, which reads the CH224A through a register-read callback, and host test are in;
  the I2C bus and rail ADC glue is not yet).
- `fwe_xover`: the subwoofer crossover DSP.
- `fwe_selftest`: the `npie-selftest/1` console (`st rails|pd|tone|net`) for bring-up (its `core/`,
  the line parsing and `OK {json}`/`ERR <reason>` framing, and host test are in; the handlers
  and the USB serial and TCP glue are not yet).
- `fwe_webapp`: the phone web app.

Nothing in upstream calls a component yet. Hooking one in (an init call, a squeezelite
DSP hook) is a patch to upstream that the follow-up row decides.
