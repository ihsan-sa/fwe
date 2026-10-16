#!/usr/bin/env python3
"""bringup_triage.py - read /npie's report of a failed bring-up step, say where to look.

/npie carries out firmware/bringup-plan.json (bringup_plan.py), stops at the
first step that fails and sends back what the plan's `on_fail.report` asks for,
as a report (schema fwe-bringup-report/1):

  {"schema": "fwe-bringup-report/1", "board": "PCB-0029-A", "step": "boot",
   "lines": ["rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))"],
   "current_a": 0.08}

This reads it against the plan and writes firmware/bringup-triage.json (schema
fwe-bringup-triage/1): the step, then `findings`, the suspects the console lines
point at first (each with the line that points there as `evidence`), then the
step's own `fwe_suspects` from the plan. Each finding has a `side`: `firmware`
is /fwe's to fix, `hardware` is a finding for hwde, `bench` is /npie's setup.
`side` at the top is the first finding's. `rerun_from` is the step /npie
starts again from once the fix lands.

  bringup_triage.py --workspace PCB-0029-A_hifi --report npie-report.json

JSON to stdout (or --out): {"ok", "path", "triage"}. Exit 0 written, 1 no plan
(run bringup_plan.py first), 2 error (a report this can't read, or a step the
plan doesn't have).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

SCHEMA = "fwe-bringup-triage/1"
REPORT = "fwe-bringup-report/1"
NAME = "bringup-triage.json"
PLAN = "bringup-plan.json"
HWDE = "finding for hwde"

# (step glob, line regex, side, suspect). The regex None matches a report
# with no console line at all. The first rule a line matches wins for it.
RULES = [
    ("*", r"Brownout detector was triggered", "hardware",
     "the 3V3 rail sags when the radio or the amplifier starts: its regulator or bulk "
     "capacitance, a " + HWDE),
    ("*", r"Guru Meditation Error|abort\(\) was called|^Backtrace:", "firmware",
     "a crash in our code: decode the Backtrace addresses against the build's ELF"),
    ("power", r".", "hardware", "a rail out of range: the power stage, a " + HWDE),
    ("flash", r"Failed to connect|Wrong boot mode|No serial data received", "hardware",
     "the boot strap or auto-reset circuit misses the ROM bootloader, a " + HWDE),
    ("flash", r"[Nn]o (debug )?probe|[Pp]ermission denied|could not open port", "bench",
     "the probe or serial port on the bench, not the board"),
    ("flash", r"MD5 of file does not match|[Vv]erif\w* (failed|error)", "firmware",
     "the flash size or mode in the write command against the part"),
    ("boot", r"^rst:0x[0-9a-f]+ \(.*boot:0x3 |DOWNLOAD_BOOT", "hardware",
     "GPIO0 still held low at reset, so the ROM waits in download mode: its strap, a " + HWDE),
    ("boot", r"flash read err|invalid header|[Ii]nvalid image", "firmware",
     "the flash mode or frequency, or the bootloader's offset, in the esptool command"),
    ("boot", r'^EVT \{"boot":.*"reset_cause":"(iwdg|wwdg)"', "firmware",
     "the watchdog fires before init feeds it: a stall in the clock or ADC setup"),
    ("boot", r'^EVT \{"boot":.*"reset_cause":"power"', "hardware",
     "a brownout reset: the 3V3 rail dips at start-up, a " + HWDE),
    ("boot", r'^EVT \{"boot":.*"reset_cause":"option_bytes"', "firmware",
     "the option bytes the flash step wrote (BOOT0, nBOOT_SEL) reset the part"),
    ("boot", None, "firmware",
     "nothing on the console: the clock tree or the console UART's pins and baud"),
    ("hook:*", r"^ERR (\S+)", "firmware", "the console handler's `{1}` error for `{send}`"),
    ("cmd:*", r"^ERR (\S+)", "firmware", "the console handler's `{1}` error for `{send}`"),
    ("hook:*", None, "firmware", "the console handler for `{send}` never answered"),
    ("cmd:*", None, "firmware", "the console handler for `{send}` never answered"),
    ("nvs:*", None, "firmware", "the key is missing: the nvs_config image's offset or the CSV row"),
]


class Error(Exception):
    pass


def _side(text: str) -> str:
    return "hardware" if HWDE in text else "firmware"


def _boot_missing(step: dict, lines: list[str]) -> list[dict]:
    """An MCU boot step that shows its banner but no EVT boot line faulted in between."""
    exp = step.get("expect")
    if step["id"] != "boot" or not isinstance(exp, list) or len(exp) < 2:
        return []
    seen = [any(re.search(e, ln) for ln in lines) for e in exp]
    if seen[0] and not seen[1]:
        return [{"side": "firmware", "evidence": next(ln for ln in lines if re.search(exp[0], ln)),
                 "suspect": "the banner came but no boot line: a fault between the console and "
                            "console_boot()"}]
    return []


def _nvs_mismatch(step: dict, lines: list[str]) -> list[dict]:
    if not step["id"].startswith("nvs:") or not lines or step["expect"] in lines:
        return []
    return [{"side": "firmware", "evidence": lines[-1],
             "suspect": f"read back differs from {step['expect']!r}: the {step['namespace']}."
                        f"{step['key']} row pinmap.py wrote"}]


def triage(plan: dict, rep: dict) -> dict:
    if not isinstance(rep, dict) or rep.get("schema") != REPORT:
        got = rep.get("schema") if isinstance(rep, dict) else type(rep).__name__
        raise Error(f"can't read a {got!r} report: only {REPORT}")
    if rep.get("board") != plan.get("board"):
        raise Error(f"the report is for {rep.get('board')!r}, the plan for {plan.get('board')!r}")
    lines = rep.get("lines", [])
    if not isinstance(lines, list) or not all(isinstance(ln, str) for ln in lines):
        raise Error("the report's lines must be a list of strings")
    ids = [s["id"] for s in plan["steps"]]
    if rep.get("step") not in ids:
        raise Error(f"the plan has no step {rep.get('step')!r}: {', '.join(ids)}")
    step = plan["steps"][ids.index(rep["step"])]
    send = step.get("send", "")
    rules = [r for r in RULES if fnmatch.fnmatchcase(step["id"], r[0])]
    found: list[dict] = []
    for _, rx, side, text in rules:
        for ln in lines if rx else []:
            m = re.search(rx, ln)
            if m and all(f["evidence"] != ln for f in found):
                found.append({"side": side, "evidence": ln,
                              "suspect": text.format(m.group(0), *m.groups(), send=send)})
    found += [f for f in _boot_missing(step, lines) + _nvs_mismatch(step, lines)
              if all(g["evidence"] != f["evidence"] for g in found)]
    found += [{"side": side, "suspect": text.format(send=send), "evidence": None}
              for _, rx, side, text in rules if rx is None and not lines][:1]
    found += [{"side": _side(s), "suspect": s, "evidence": None}
              for s in step["fwe_suspects"] if all(f["suspect"] != s for f in found)]
    return {"schema": SCHEMA, "board": plan["board"], "stage": plan.get("stage"),
            "version": plan.get("version"), "step": step["id"], "side": found[0]["side"],
            "current_a": rep.get("current_a"), "findings": found, "rerun_from": step["id"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--report", required=True, help="/npie's report (fwe-bringup-report/1)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    fw = fwenv.workspace(a.workspace) / "firmware"
    src = fw / PLAN
    if not src.is_file():
        fwenv.emit({"ok": False, "error": f"no {src}: run bringup_plan.py first"}, a.out)
        return 1
    try:
        t = triage(json.loads(src.read_text(encoding="utf-8")),
                   json.loads(Path(a.report).read_text(encoding="utf-8")))
    except (Error, ValueError, OSError, KeyError) as e:
        fwenv.emit({"ok": False, "error": str(e)}, a.out)
        return 2
    path = fw / NAME
    path.write_text(json.dumps(t, indent=2) + "\n", encoding="utf-8")
    fwenv.emit({"ok": True, "path": str(path), "triage": t}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
