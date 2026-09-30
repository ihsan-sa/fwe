#!/usr/bin/env python3
"""fw_sim.py - boot the built firmware in Renode and talk to its console.

A smoke test, not a hardware claim. The platform is firmware/sim/g431.repl:
core, memory, NVIC and USART1 are modelled; RCC and ADC1/2 are read-back
stubs (every conversion reads mid-scale, so ~0 A and a ~26 V bus) and every
other peripheral reads 0. So a pass means the ELF boots, the clock code
finishes, the console prints its banner and answers commands; it says nothing
about PWM, the real ADC, the gate driver or the fault thresholds.

  fw_sim.py --workspace PCB-0018-A_bldc-motor-driver [--send version --send status]

Steps: copy sim/ to a temp dir, write a .resc that loads the ELF, sends each
--send line on USART1 after boot, runs --seconds of wall time, and reads the
UART back from a file. Pass = the banner matches the manifest's regex
(`^fwe <board> `), a boot EVT follows, and every sent command gets one
`OK`/`ERR` reply line.

JSON to stdout (or --out): {"ok", "banner", "replies": [{send, reply}],
"uart": [lines], "log_tail"}. Exit 0 pass, 1 fail, 2 error (no Renode, no
build, no sim/ in the project).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402


def renode() -> Path | None:
    for t in fwenv.lock()["tarballs"]:
        if t["name"] == "renode":
            p = fwenv.tool_root(t) / t["bin"] / "renode"
            return p if p.is_file() else None
    return None


def board_id(ws: Path) -> str:
    return ws.name.split("_", 1)[0]


def script(tmp: Path, elf: Path, sends: list[str], boot_s: float) -> str:
    lines = ['mach create "fwe"',
             f"machine LoadPlatformDescription @{tmp / 'g431.repl'}",
             f"sysbus LoadELF @{elf}",
             f"usart1 CreateFileBackend @{tmp / 'uart.txt'} true",
             "logLevel 3", "start", f"sleep {boot_s:g}"]
    for s in sends:
        lines += [f"usart1 WriteChar 0x{ord(ch):02x}" for ch in s + "\n"]
        lines.append("sleep 0.5")
    return "\n".join(lines) + "\n"


def run(ws: Path, sends: list[str], seconds: float, boot_s: float) -> tuple[int, dict]:
    fw = ws / "firmware"
    elf, sim = fw / "build" / "fw.elf", fw / "sim"
    rn = renode()
    if not rn:
        return 2, {"ok": False, "error": "renode not installed: run fwe_setup.py"}
    if not elf.is_file():
        return 2, {"ok": False, "error": f"no {elf}: run fw_build.py"}
    if not (sim / "g431.repl").is_file():
        return 2, {"ok": False, "error": f"no {sim}/g431.repl: re-run fw_scaffold.py"}
    with tempfile.TemporaryDirectory(prefix="fwe-sim-") as d:
        tmp = Path(d)
        for f in sim.iterdir():
            if f.is_file():
                shutil.copy(f, tmp / f.name)
        repl = tmp / "g431.repl"
        repl.write_text(repl.read_text(encoding="utf-8").replace("@SIMDIR@", str(tmp)), encoding="utf-8")
        (tmp / "smoke.resc").write_text(script(tmp, elf, sends, boot_s), encoding="utf-8")
        cmd = [str(rn), "--disable-gui", "--console", "-e",
               f"include @{tmp / 'smoke.resc'}; sleep {seconds:g}; quit"]
        try:
            p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                               timeout=seconds + 30 + len(sends))
            log = p.stdout + p.stderr
        except subprocess.TimeoutExpired:
            log = "renode timed out"
        uart_f = tmp / "uart.txt"
        uart = uart_f.read_text(encoding="utf-8", errors="replace") if uart_f.is_file() else ""
    lines = [ln.strip() for ln in uart.splitlines() if ln.strip()]
    banner = next((ln for ln in lines if re.match(rf"^fwe {re.escape(board_id(ws))} ", ln)), None)
    boot = any(ln.startswith('EVT {"boot"') for ln in lines)
    answers = [ln for ln in lines if re.match(r"^(OK|ERR)\b", ln)]
    replies = [{"send": s, "reply": answers[i] if i < len(answers) else None}
               for i, s in enumerate(sends)]
    ok = bool(banner) and boot and all(r["reply"] for r in replies)
    tail = "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", log).strip().splitlines()[-15:])
    return (0 if ok else 1), {"ok": ok, "simulator": "renode", "banner": banner, "boot_evt": boot,
                              "replies": replies, "uart": lines, "log_tail": tail}


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
