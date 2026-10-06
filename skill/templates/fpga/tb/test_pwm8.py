"""test_pwm8.py - cocotb bench for pwm8_ctrl: phase step, 8-channel skew,
atomic commit, duty limits, enable, the UART register protocol, and the
per-channel skew trim (coarse steps plus delay-line taps).

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
F_RF = 13.56e6       # the design's carrier: a step is 1 / (N * F_RF)
TAP_S = 25e-12       # DELAYF's nominal tap; the real one is calibrated on the bench
TAPS = 128


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
    await ClockCycles(dut.clk, 4)          # stop bit sampled, then three clocks
    assert int(dut.word.value) == 0, "outputs still high after disable"
    assert await r == ord("K")


def taps(dut):
    return [int(getattr(dut, "line")[k].dl.tap.value) for k in range(CH)]


def moves(dut):
    return [int(getattr(dut, "line")[k].dl.moves.value) for k in range(CH)]


async def taps_settled(dut, cpb):
    for _ in range(100):
        if await read(dut, cpb, 0x01) & 8 == 0:
            return taps(dut)
    raise AssertionError("the delay lines never settled (ctrl bit3 stuck)")


def calibration(delay_s, step_s, tap_s=TAP_S):
    """The trim table for measured channel delays: hold every channel back to
    the latest one, whole steps first and the rest in taps."""
    late = max(delay_s)
    table = []
    for d in delay_s:
        c = int((late - d) // step_s)
        table.append((c, round((late - d - c * step_s) / tap_s)))
    return table


@cocotb.test()
async def test_coarse_trim_delays_the_edge_and_lands_on_commit(dut):
    n, w, cpb = await reset(dut)
    assert await read(dut, cpb, 0x05) == TAPS
    await program(dut, cpb, [3] * CH, [n // 2] * CH)
    await settle(dut, n, w)
    trim = [0, 1, 2, w, w + 1, n - 3, n - 1, 5]
    for k in range(CH):
        await write(dut, cpb, 0x20 + k, trim[k])
    s = await capture(dut, n, w, 1)
    assert all(rising(s[k] * 2)[0] == 3 for k in range(CH)), "a trim moved an edge before commit"
    assert [await read(dut, cpb, 0x20 + k) for k in range(CH)] == trim
    await write(dut, cpb, 0x01, 3)
    await settle(dut, n, w)
    s = await capture(dut, n, w, 2)
    for k in range(CH):
        want = (3 + trim[k]) % n
        assert {e % n for e in rising(s[k])} == {want}, f"ch{k}: edges {rising(s[k])}, want {want}"
        assert sum(s[k]) == n // 2 * 2, f"ch{k}: the trim changed the duty"
    await write(dut, cpb, 0x20, n, expect=b"E")
    await write(dut, cpb, 0x28, TAPS, expect=b"E")
    assert await read(dut, cpb, 0x20) == trim[0] and await read(dut, cpb, 0x28) == 0


@cocotb.test()
async def test_fine_trim_walks_each_delay_line_to_its_tap(dut):
    n, w, cpb = await reset(dut)
    fine = [0, 1, TAPS - 1, 64, 5, 53, 10, 100]
    for k in range(CH):
        await write(dut, cpb, 0x28 + k, fine[k])
    await ClockCycles(dut.clk, 4 * TAPS)
    assert taps(dut) == [0] * CH, "a delay line moved before commit"
    await write(dut, cpb, 0x01, 2)        # commit, outputs still off
    assert await taps_settled(dut, cpb) == fine
    assert moves(dut) == fine, "a line overshot and came back"
    # walk back down: every line takes the shortest way, one tap per move
    back = [3, 0, 120, 64, 0, 20, 11, 99]
    for k in range(CH):
        await write(dut, cpb, 0x28 + k, back[k])
    await write(dut, cpb, 0x01, 2)
    assert await taps_settled(dut, cpb) == back
    assert moves(dut) == [f + abs(f - b) for f, b in zip(fine, back)]
    assert [await read(dut, cpb, 0x28 + k) for k in range(CH)] == back


@cocotb.test()
async def test_calibration_table_brings_the_skew_under_a_tenth_of_a_ns(dut):
    n, w, cpb = await reset(dut)
    step = 1 / (n * F_RF)
    # the boards seat's worst case: 3.59 ns from first to last channel, uncalibrated
    delay = [d * 1e-9 for d in (0.00, 3.59, 1.27, 2.64, 0.41, 3.05, 1.88, 0.93)]
    table = calibration(delay, step)
    assert max(c for c, _ in table) >= 1 and max(f for _, f in table) < TAPS
    for k, (c, f) in enumerate(table):
        await write(dut, cpb, 0x20 + k, c)
        await write(dut, cpb, 0x28 + k, f)
    await program(dut, cpb, [0] * CH, [n // 2] * CH)
    await settle(dut, n, w)
    tap = await taps_settled(dut, cpb)
    s = await capture(dut, n, w, 2)
    edge = [rising(s[k])[0] for k in range(CH)]
    assert edge == [c for c, _ in table], f"coarse trims not applied: edges {edge}"
    arrive = [delay[k] + edge[k] * step + tap[k] * TAP_S for k in range(CH)]
    span = max(arrive) - min(arrive)
    assert span <= TAP_S + 1e-15, f"calibrated skew {span * 1e12:.0f} ps, over one tap"
    assert span < 0.1e-9 < max(delay) - min(delay)
