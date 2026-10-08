#!/usr/bin/env python3
"""fw_sim.py - boot the built firmware in Renode and talk to its console.

A smoke test, not a hardware claim. The platform is the one *.repl in
firmware/sim/ (g431.repl for the STM32G431 motor boards, g474.repl for the
STM32G474 HRTIM boost); its first UART peripheral is the console (usart1 on
the G431, usart2 on the G474). Core, memory, NVIC and that UART are
modelled; RCC and ADC1/2 are read-back stubs (every conversion reads
mid-scale) and other peripherals read 0 unless the repl stubs them.

G431: a pass means the ELF boots, the clock code finishes, the console prints
its banner and answers commands; it says nothing about PWM, the real ADC, the
gate driver or the fault thresholds.

G474 (the repl has the hrtim.py stub): the same, plus an HRTIM scenario. After
the sends it sends `arm`, reads HRTIM Timer A PER, CMP1, DT and the output
enables (OENR) from the monitor, asserts FLTn of the board's OVP comparator
(TRIP_OVP_FLT in gen/board_pins.h, FLT5 = COMP3) through the stub's inject
register, reads OENR and ISR again and sends `status`. Pass also needs PER at
the board's PWM_FREQ_HZ (+-1%, fsw = fHRTIM x 32 / PER), both dead times
within one tDTG of DEADTIME_NS (tDTG = 2^DTPRSC / (8 fHRTIM), RM0440 28.3.4
Table 237), both outputs disabled after the fault and the status after it
reporting the trip latched. What that proves: the firmware programs the
period, dead time and fault enables (the stub only trips a fault the firmware
enabled on FLTINRx and Timer A) and latches and reports the FLTn flag. What it
does not: no counter runs and no edge exists, the DLL, comparators, DACs and
the ADC trigger are stubs or absent, so no ADC interrupt ever fires; the
firmware then sees its control sample stale and refuses `arm` (ERR hw), so
the outputs are off before the fault too and the "outputs drop on a fault"
step is the stub's behaviour, not a measurement.

  fw_sim.py --workspace PCB-0018-A_bldc-motor-driver [--send version --send status]

Steps: copy sim/ to a temp dir, write a .resc that loads the ELF, sends each
--send line on the console UART after boot, runs the HRTIM scenario if any,
runs --seconds of wall time, and reads the UART back from a file and the
monitor's register reads from Renode's stdout. Pass = the banner matches the
manifest's regex (`^fwe <board> `), a boot EVT follows, every sent command
gets one `OK`/`ERR` reply line, and the HRTIM checks above when they apply.

JSON to stdout (or --out): {"ok", "repl", "uart_name", "banner", "replies":
[{send, reply}], "uart": [lines], "log_tail"} and, for the G474, "hrtim":
{per, cmp1, dt, fsw_hz, dead_time_ns: {rise, fall}, outputs_before,
outputs_after_trip, isr_after_trip, trip_evt, arm_reply, status_after_trip,
checks}. Exit 0 pass, 1 fail, 2 error (no Renode, no build, not exactly one
*.repl in sim/).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

HRTIM_BASE = 0x40016800                      # RM0440 Rev 9, chapter 28
HR_REGS = {"PER": 0x94, "CMP1": 0x9C, "DT": 0xB8,      # Timer A (TIMxPERAR, CMP1AR, DTAR)
           "OENR": 0x394, "ISR": 0x388}                # common
HR_INJECT = 0xBF0                            # hrtim.py's sim-only fault inject
OUT_TA = 0x3                                 # TA1OEN | TA2OEN
DEFAULTS = {"PWM_FREQ_HZ": 1_000_000, "DEADTIME_NS": 10, "HRTIM_FHRTIM_HZ": 170_000_000,
            "TRIP_OVP_FLT": 5}


def renode() -> Path | None:
    for t in fwenv.lock()["tarballs"]:
        if t["name"] == "renode":
            p = fwenv.tool_root(t) / t["bin"] / "renode"
            return p if p.is_file() else None
    return None


def board_id(ws: Path) -> str:
    return ws.name.split("_", 1)[0]


def find_repl(sim: Path) -> tuple[Path | None, str | None]:
    """The single *.repl in sim/, or an error."""
    repls = sorted(sim.glob("*.repl")) if sim.is_dir() else []
    if not repls:
        return None, f"no *.repl in {sim}: re-run fw_scaffold.py"
    if len(repls) > 1:
        return None, f"several *.repl in {sim} ({', '.join(p.name for p in repls)}): keep one"
    return repls[0], None


def console_uart(repl_text: str) -> str | None:
    """The first UART.* peripheral's name: the firmware's console."""
    m = re.search(r"^(\w+)\s*:\s*UART\.", repl_text, re.M)
    return m.group(1) if m else None


def has_hrtim(repl_text: str) -> bool:
    return re.search(r'filename:\s*"[^"]*hrtim\.py"', repl_text) is not None


def fw_defines(fw: Path) -> dict:
    """PWM_FREQ_HZ, DEADTIME_NS, HRTIM_FHRTIM_HZ and TRIP_OVP_FLT from the
    project's headers, the DEFAULTS where a header does not say."""
    out = dict(DEFAULTS)
    for h in (fw / "config" / "fw_config.h", fw / "gen" / "board_pins.h"):
        text = h.read_text(encoding="utf-8") if h.is_file() else ""
        for k in out:
            m = re.search(rf"^#define\s+{k}\s+(\d+)[uUlL]*\b", text, re.M)
            if m:
                out[k] = int(m.group(1))
    return out


def hr_read(name: str) -> list[str]:
    return [f'echo "HR {name}"', f"sysbus ReadDoubleWord 0x{HRTIM_BASE + HR_REGS[name]:08X}"]


def send_lines(uart: str, s: str) -> list[str]:
    return [f"{uart} WriteChar 0x{ord(ch):02x}" for ch in s + "\n"] + ["sleep 0.5"]


def script(tmp: Path, repl: str, uart: str, elf: Path, sends: list[str], boot_s: float,
           inject: int | None = None) -> str:
    lines = ['mach create "fwe"',
             f"machine LoadPlatformDescription @{tmp / repl}",
             f"sysbus LoadELF @{elf}",
             f"{uart} CreateFileBackend @{tmp / 'uart.txt'} true",
             "logLevel 3", "start", f"sleep {boot_s:g}"]
    for s in sends:
        lines += send_lines(uart, s)
    if inject is not None:
        lines += send_lines(uart, "arm")
        for r in ("PER", "CMP1", "DT", "OENR"):
            lines += hr_read(r)
        lines += [f"sysbus WriteDoubleWord 0x{HRTIM_BASE + HR_INJECT:08X} {inject}", "sleep 0.5",
                  'echo "HR TRIP"']
        for r in ("OENR", "ISR"):
            lines += hr_read(r)
        lines += send_lines(uart, "status")
    return "\n".join(lines) + "\n"


def parse_monitor(log: str) -> dict:
    """{reg: value} from the `echo "HR <reg>"` markers, each followed by the
    monitor's 0x... answer; reads after the `HR TRIP` marker get `_after`."""
    vals, want, after = {}, None, False
    for ln in re.sub(r"\x1b\[[0-9;]*m", "", log).splitlines():
        ln = ln.strip()
        m = re.fullmatch(r"HR (\w+)", ln)
        if m:
            if m.group(1) == "TRIP":
                after, want = True, None
            else:
                want = m.group(1) + ("_after" if after else "")
            continue
        if want and re.fullmatch(r"0x[0-9A-Fa-f]+", ln):
            vals[want], want = int(ln, 16), None
    return vals


def hrtim_result(vals: dict, uart: list[str], defs: dict, arm_reply: str | None,
                 status_reply: str | None) -> dict:
    """The HRTIM block and its pass checks (see the docstring)."""
    fhr = defs["HRTIM_FHRTIM_HZ"]
    per, cmp1, dt = vals.get("PER"), vals.get("CMP1"), vals.get("DT")
    fsw = fhr * 32 / per if per else None                      # CKPSC = 0: fHRTIM x 32
    dead = None
    if dt is not None:
        t_dtg = 2 ** ((dt >> 10) & 0x7) / (8 * fhr) * 1e9      # ns, RM0440 28.3.4 Table 237
        dead = {"rise": round((dt & 0x1FF) * t_dtg, 3), "fall": round(((dt >> 16) & 0x1FF) * t_dtg, 3),
                "step": round(t_dtg, 3)}
    status = None
    if status_reply and status_reply.startswith("OK "):
        try:
            status = json.loads(status_reply[3:])
        except ValueError:
            status = None
    trip_evt = next((ln for ln in uart if ln.startswith('EVT {"trip"')), None)
    before, after = vals.get("OENR"), vals.get("OENR_after")
    checks = {
        "fsw": fsw is not None and abs(fsw - defs["PWM_FREQ_HZ"]) <= 0.01 * defs["PWM_FREQ_HZ"],
        "dead_time": dead is not None and all(abs(dead[k] - defs["DEADTIME_NS"]) <= dead["step"]
                                              for k in ("rise", "fall")),
        "outputs_off_after_trip": after is not None and (after & OUT_TA) == 0,
        "trip_latched": bool(status) and "ovp_hw" in status.get("trips", [])
                        and status.get("outputs_on") is False,
    }
    return {"per": per, "cmp1": cmp1, "dt": None if dt is None else f"0x{dt:08X}",
            "fsw_hz": None if fsw is None else round(fsw, 1), "dead_time_ns": dead,
            "outputs_before": before, "outputs_after_trip": after,
            "isr_after_trip": vals.get("ISR_after"), "trip_evt": trip_evt,
            "arm_reply": arm_reply, "status_after_trip": status_reply, "checks": checks}


def run(ws: Path, sends: list[str], seconds: float, boot_s: float) -> tuple[int, dict]:
    fw = ws / "firmware"
    elf, sim = fw / "build" / "fw.elf", fw / "sim"
    rn = renode()
    if not rn:
        return 2, {"ok": False, "error": "renode not installed: run fwe_setup.py"}
    if not elf.is_file():
        return 2, {"ok": False, "error": f"no {elf}: run fw_build.py"}
    repl_src, err = find_repl(sim)
    if err:
        return 2, {"ok": False, "error": err}
    repl_text = repl_src.read_text(encoding="utf-8")
    uart = console_uart(repl_text)
    if not uart:
        return 2, {"ok": False, "error": f"{repl_src.name} has no UART.* peripheral for the console"}
    defs = fw_defines(fw)
    inject = defs["TRIP_OVP_FLT"] if has_hrtim(repl_text) else None
    with tempfile.TemporaryDirectory(prefix="fwe-sim-") as d:
        tmp = Path(d)
        for f in sim.iterdir():
            if f.is_file():
                shutil.copy(f, tmp / f.name)
        (tmp / repl_src.name).write_text(repl_text.replace("@SIMDIR@", str(tmp)), encoding="utf-8")
        (tmp / "smoke.resc").write_text(script(tmp, repl_src.name, uart, elf, sends, boot_s, inject),
                                        encoding="utf-8")
        cmd = [str(rn), "--disable-gui", "--console", "-e",
               f"include @{tmp / 'smoke.resc'}; sleep {seconds:g}; quit"]
        extra = 0 if inject is None else 4
        try:
            p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                               timeout=seconds + 30 + len(sends) + extra)
            log = p.stdout + p.stderr
        except subprocess.TimeoutExpired:
            log = "renode timed out"
        uart_f = tmp / "uart.txt"
        text = uart_f.read_text(encoding="utf-8", errors="replace") if uart_f.is_file() else ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    banner = next((ln for ln in lines if re.match(rf"^fwe {re.escape(board_id(ws))} ", ln)), None)
    boot = any(ln.startswith('EVT {"boot"') for ln in lines)
    answers = [ln for ln in lines if re.match(r"^(OK|ERR)\b", ln)]
    replies = [{"send": s, "reply": answers[i] if i < len(answers) else None}
               for i, s in enumerate(sends)]
    ok = bool(banner) and boot and all(r["reply"] for r in replies)
    tail = "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", log).strip().splitlines()[-15:])
    res = {"ok": ok, "simulator": "renode", "repl": repl_src.name, "uart_name": uart,
           "banner": banner, "boot_evt": boot, "replies": replies}
    if inject is not None:
        n = len(sends)
        hr = hrtim_result(parse_monitor(log), lines, defs,
                          answers[n] if n < len(answers) else None,
                          answers[n + 1] if n + 1 < len(answers) else None)
        hr["fault_injected"] = f"FLT{inject}"
        res["hrtim"] = hr
        res["ok"] = ok = ok and all(hr["checks"].values())
    res.update({"uart": lines, "log_tail": tail})
    return (0 if ok else 1), res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--send", action="append", help="a console line to send after boot (repeatable; "
                    "default: version, status)")
    ap.add_argument("--boot", type=float, default=4.0, help="wall seconds to let it boot before sending")
    ap.add_argument("--seconds", type=float, default=3.0, help="wall time to run after the script")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = run(ws, a.send or ["version", "status"], a.seconds, a.boot)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
