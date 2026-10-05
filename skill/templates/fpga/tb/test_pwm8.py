"""test_pwm8.py - cocotb bench for pwm8_ctrl: phase step, 8-channel skew,
atomic commit, duty limits, enable, and the UART register protocol.

Run by scripts/fpga_sim.py through chip-flow's cocotblib (Icarus). Every
test resets the design and builds its own state. `steps(ch)` rebuilds the
serial stream a channel's serialiser would send, one entry per step, from
the words the core emits; edges and skew are counted in steps, and a step
is 1 / (N * f_rf).
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

CH = 8


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.uart_rx.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    return int(dut.p_n.value), int(dut.p_w.value), int(dut.p_cpb.value)


async def send(dut, byte, cpb):
    for bit in [0] + [(byte >> i) & 1 for i in range(8)] + [1]:
        dut.uart_rx.value = bit
        await ClockCycles(dut.clk, cpb)


async def recv(dut, cpb):
    for _ in range(40 * cpb):
        await RisingEdge(dut.clk)
        if dut.uart_tx.value == 0:
            break
    else:
        raise AssertionError("no reply on uart_tx")
    await ClockCycles(dut.clk, cpb // 2)
    byte = 0
    for i in range(8):
        await ClockCycles(dut.clk, cpb)
        byte |= int(dut.uart_tx.value) << i
    await ClockCycles(dut.clk, cpb)
    assert dut.uart_tx.value == 1, "stop bit"
    return byte


async def cmd(dut, cpb, *data):
    r = cocotb.start_soon(recv(dut, cpb))
    for b in data:
        await send(dut, b, cpb)
    return await r


async def write(dut, cpb, addr, val, expect=b"K"):
    got = await cmd(dut, cpb, ord("W"), addr, val)
    assert got == expect[0], f"W {addr:#x} {val}: got {chr(got)!r}"


async def read(dut, cpb, addr):
    return await cmd(dut, cpb, ord("R"), addr)


async def program(dut, cpb, phases, duties, enable=1):
    for k in range(CH):
        await write(dut, cpb, 0x10 + k, phases[k])
        await write(dut, cpb, 0x18 + k, duties[k])
    await write(dut, cpb, 0x01, enable | 2)


async def capture(dut, n, w, periods):
    """The stream of each channel for whole periods, from a period start."""
    while True:
        await FallingEdge(dut.clk)
        if dut.period_start.value == 1:
            break
    words = []
    for _ in range(periods * n // w):
        words.append(int(dut.word.value))
        await FallingEdge(dut.clk)
    return [[(x >> (k * w + j)) & 1 for x in words for j in range(w)] for k in range(CH)]


def rising(stream):
    return [i for i in range(len(stream)) if stream[i] and not stream[i - 1]]


async def settle(dut, n, w):
    # a commit lands at the next period start; skip one whole period after it
    await ClockCycles(dut.clk, 2 * n // w + 2)


@cocotb.test()
async def test_outputs_low_from_reset(dut):
    n, w, cpb = await reset(dut)
    s = await capture(dut, n, w, 2)
    assert all(not any(c) for c in s), "an output is high before any command"
    await write(dut, cpb, 0x01, 1)        # enable with every duty still 0
    await settle(dut, n, w)
    s = await capture(dut, n, w, 2)
    assert all(not any(c) for c in s), "enable alone drove an output"


@cocotb.test()
async def test_id_and_geometry_read_back(dut):
    n, w, cpb = await reset(dut)
    assert await read(dut, cpb, 0x00) == 0xF8
    assert (await read(dut, cpb, 0x02), await read(dut, cpb, 0x03),
            await read(dut, cpb, 0x04)) == (n, w, CH)
    assert await read(dut, cpb, 0x40) == ord("E")
    assert await cmd(dut, cpb, ord("x")) == ord("?")


@cocotb.test()
async def test_phase_moves_the_edge_one_step_per_count(dut):
    n, w, cpb = await reset(dut)
    half = n // 2
    for p in (0, 1, 2, 3, w - 1, w, w + 1, n // 2, n - 1):
        await program(dut, cpb, [p] + [0] * (CH - 1), [half] * CH)
        await settle(dut, n, w)
        s = await capture(dut, n, w, 3)
        assert rising(s[0]) == [p + i * n for i in range(3)], \
            f"phase {p}: rising edges at {rising(s[0])}"
        assert sum(s[0]) == 3 * half, f"phase {p}: duty changed with phase"
        # channel 1 sits at phase 0, so the skew between the two is p steps
        assert s[0] == s[1][-p:] + s[1][:-p] if p else s[0] == s[1]


@cocotb.test()
async def test_eight_channels_hold_zero_skew_and_set_skew(dut):
    n, w, cpb = await reset(dut)
    await program(dut, cpb, [0] * CH, [n // 2] * CH)
    await settle(dut, n, w)
    s = await capture(dut, n, w, 2)
    assert all(s[k] == s[0] for k in range(CH)), "equal phases are not in step"
    assert sum(s[0]) == n, "two periods at 50% duty"
    # a spread that crosses word boundaries and the period wrap
    phases = [(k * 9 + 5) % n for k in range(CH)]
    await program(dut, cpb, phases, [n // 3] * CH)
    await settle(dut, n, w)
    s = await capture(dut, n, w, 2)
    for k in range(CH):
        first = [e % n for e in rising(s[k])]
        assert set(first) == {phases[k]}, f"ch{k}: edges {rising(s[k])}, want phase {phases[k]}"


@cocotb.test()
async def test_commit_applies_all_channels_in_the_same_period(dut):
    n, w, cpb = await reset(dut)
    await program(dut, cpb, [0] * CH, [n // 2] * CH)
    await settle(dut, n, w)
    for k in range(CH):                    # new phases, no commit yet
        await write(dut, cpb, 0x10 + k, 7)
    s = await capture(dut, n, w, 1)
    assert all(rising(s[k] * 2)[0] == 0 for k in range(CH)), "a phase moved before commit"
    assert await read(dut, cpb, 0x01) & 4 == 0
    # capture across the commit: the three command bytes take 30 bit times
    periods = 30 * cpb * w // n + 4
    cap = cocotb.start_soon(capture(dut, n, w, periods))
    await write(dut, cpb, 0x01, 3)
    s = await cap
    old = [1] * (n // 2) + [0] * (n - n // 2)
    new = old[-7:] + old[:-7]
    for k in range(CH):
        got = [s[k][i * n:(i + 1) * n] for i in range(periods)]
        # every period is wholly old or wholly new: the commit lands on a period start
        assert all(p in (old, new) for p in got), f"ch{k}: a period mixes old and new phase"
        assert got[0] == old and got[-1] == new, f"ch{k}: the commit did not land"
        if k == 0:
            switch = got.index(new)
        assert got.index(new) == switch, f"ch{k} switched in period {got.index(new)}, ch0 in {switch}"


@cocotb.test()
async def test_duty_limits_and_range_checks(dut):
    n, w, cpb = await reset(dut)
    duties = [0, n, 1, n - 1, n // 2, n // 4, 3, 5]
    await program(dut, cpb, [3] * CH, duties)
    await settle(dut, n, w)
    s = await capture(dut, n, w, 2)
    for k in range(CH):
        assert sum(s[k]) == 2 * duties[k], f"ch{k}: duty {duties[k]} gave {sum(s[k]) / 2}"
    await write(dut, cpb, 0x10, n, expect=b"E")
    await write(dut, cpb, 0x18, n + 1, expect=b"E")
    await write(dut, cpb, 0x02, 1, expect=b"E")
    assert await read(dut, cpb, 0x10) == 3 and await read(dut, cpb, 0x18) == 0


@cocotb.test()
async def test_disable_turns_outputs_off_at_once(dut):
    n, w, cpb = await reset(dut)
    await program(dut, cpb, [0] * CH, [n] * CH)
    await settle(dut, n, w)
    s = await capture(dut, n, w, 1)
    assert all(all(c) for c in s)
    r = cocotb.start_soon(recv(dut, cpb))
    for b in (ord("W"), 0x01, 0x00):
        await send(dut, b, cpb)
    await ClockCycles(dut.clk, 3)          # stop bit sampled, then two clocks
    assert int(dut.word.value) == 0, "outputs still high after disable"
    assert await r == ord("K")
