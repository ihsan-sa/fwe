# esp32-test

`esp32_test.py --workspace <board>` compiles each `firmware/tests/host/test_*.c` with the
host gcc (or clang) against every `components/fwe_*/core/*.c`, with
`-Wall -Wextra -Werror`, and runs it; exit 0 from the test is a pass. Only our logic is
tested here, never upstream. Keep ESP-IDF headers out of `core/`, or the host build fails:
that split is what makes the logic testable without the chip.
