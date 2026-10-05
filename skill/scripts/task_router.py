#!/usr/bin/env python3
"""task_router.py - the front door of /fwe: match a task to a verb, plan it.

VERBS below is the whole table: each verb has the regexes that pick it, a
one-line summary, the steps (script commands bound to the workspace, or
`agent:` steps the session does itself) and its recipe doc
reference/recipes/<verb>.md, which the session reads before executing.
A task that names an FPGA (fpga, gateware, verilog, rtl, bitstream, serdes,
yosys, nextpnr, cocotb) matches only the `fpga-*` verbs; any other task
matches only the MCU verbs.

  task_router.py --task "build the firmware" --workspace PCB-0018-A_bldc-motor-driver
  task_router.py --verb test --workspace <board>
  task_router.py --list        # the verb table
  task_router.py --validate    # every step's script and every recipe exists

JSON to stdout (or --out). Exit 0 one verb planned; 1 a decision is needed
(`status`: ambiguous -> pick among `candidates` and re-run with --verb;
unknown -> classify against --list or ask; needs_args -> the workspace is
missing); 2 error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
RECIPES = fwenv.SKILL / "reference" / "recipes"
PY = "python3"  # the scripts need only the standard library (SKILL.md)

VERBS = {
    "setup": {
        "match": [r"\b(setup|install|toolchain|fetch)\b"],
        "summary": "install or check the pinned toolchain and CMSIS in ~/.local/fwe-tools",
        "workspace": False,
        "steps": ["fwe_setup.py"],
    },
    "pinmap": {
        "match": [r"\bpin ?map\b", r"\bpins?\b.*\b(drift|board|netlist)\b", r"\bregenerate\b"],
        "summary": "derive firmware/pinmap.json + gen/board_pins.h from the board's netlist",
        "steps": ["pinmap.py --workspace {ws}"],
    },
    "scaffold": {
        "match": [r"\b(scaffold|new firmware|start (a |the )?firmware|create (a |the )?firmware)\b"],
        "summary": "start firmware/ from the MCU family's template (never overwrites a file)",
        "steps": ["fw_scaffold.py --workspace {ws}"],
    },
    "build": {
        "match": [r"\b(build|compile|werror|warnings?)\b"],
        "summary": "pin-map drift check, then cross-build with warnings as errors",
        "steps": ["fw_build.py --workspace {ws}"],
    },
    "test": {
        "match": [r"\b(unit ?tests?|host tests?|test the (math|control))\b", r"^test\b"],
        "summary": "compile and run the host unit tests of the control math",
        "steps": ["fw_test.py --workspace {ws}"],
    },
    "sim": {
        "match": [r"\b(sim|simulat\w*|renode|qemu|smoke)\b"],
        "summary": "boot the built ELF in Renode and check the console answers (a smoke test, not hardware)",
        "steps": ["fw_sim.py --workspace {ws}"],
    },
    "manifest": {
        "match": [r"\bmanifest\b", r"\b(npie|hand ?off|flash command)\b"],
        "summary": "write or check firmware/fwe-manifest.json, the interface /npie flashes and drives",
        "steps": ["fw_manifest.py --workspace {ws}"],
    },
    "stage": {
        "match": [r"\b(stage|six.?step|foc|commutat\w*|bring.?up firmware|add (a )?command)\b"],
        "summary": "write or extend a firmware stage (bringup, motor), then build + test",
        "steps": ["agent: write the stage per the recipe", "fw_build.py --workspace {ws}",
                  "fw_test.py --workspace {ws}"],
    },
    "review": {
        "match": [r"\b(review|audit|check the firmware)\b"],
        "summary": "review firmware against the board, the safety defaults and the manifest",
        "steps": ["pinmap.py --workspace {ws} --check", "fw_build.py --workspace {ws}",
                  "fw_test.py --workspace {ws}", "fw_manifest.py --workspace {ws} --check",
                  "agent: read the diff against the recipe's list"],
    },
    "fpga-setup": {
        "fpga": True,
        "match": [r"\b(setup|install|toolchain|tools?)\b"],
        "summary": "check the gateware tools: chip-flow's eda (iverilog, verilator, yosys, cocotb) and nextpnr",
        "workspace": False,
        "steps": ["fpga_setup.py"],
    },
    "fpga-scaffold": {
        "fpga": True,
        "match": [r"\b(scaffold|new|start|create)\b"],
        "summary": "start firmware/ as a gateware project from templates/fpga (never overwrites a file)",
        "steps": ["fpga_scaffold.py --workspace {ws}",
                  "agent: fill gateware.json `board` from firmware/README.md when it exists"],
    },
    "fpga-build": {
        "fpga": True,
        "match": [r"\b(build|synth\w*|lint|bitstream|place|route|pnr|nextpnr)\b"],
        "summary": "lint and synthesise the core; the bitstream refuses until the board stage adds its top",
        "steps": ["fpga_build.py --workspace {ws}"],
    },
    "fpga-sim": {
        "fpga": True,
        "match": [r"\b(sim\w*|test\w*|testbench|bench|cocotb|verify)\b"],
        "summary": "run the cocotb bench over Icarus through /vde's cocotblib (phase step, skew, commit)",
        "steps": ["fpga_sim.py --workspace {ws}"],
    },
    "fpga-manifest": {
        "fpga": True,
        "match": [r"\bmanifest\b", r"\b(npie|hand ?off|instrument)\b"],
        "summary": "write or check firmware/fwe-manifest.json, the interface /npie programs and drives",
        "steps": ["fpga_manifest.py --workspace {ws}"],
    },
    "fpga-review": {
        "fpga": True,
        "match": [r"\b(review|audit)\b"],
        "summary": "review the gateware against the bench, the board handoff and the manifest",
        "steps": ["fpga_build.py --workspace {ws} --synth-only", "fpga_sim.py --workspace {ws}",
                  "fpga_manifest.py --workspace {ws} --check",
                  "agent: read the diff against the recipe's list"],
    },
    "full-run": {
        "match": [r"\b(full.?run|end to end|from scratch|firmware for)\b", r"^run (on|for)\b"],
        "summary": "the whole path for a board: setup, scaffold, build, host tests",
        "steps": ["fwe_setup.py", "fw_scaffold.py --workspace {ws}",
                  "agent: fill the bringup stage per recipes/stage.md",
                  "fw_build.py --workspace {ws}", "fw_test.py --workspace {ws}",
                  "fw_sim.py --workspace {ws}", "fw_manifest.py --workspace {ws} --sim renode"],
    },
}


def bind(step: str, ws: str | None) -> dict:
    if step.startswith("agent:"):
        return {"kind": "agent", "do": step[len("agent:"):].strip()}
    cmd = step.format(ws=ws or "{ws}")
    script, _, args = cmd.partition(" ")
    return {"kind": "script", "cmd": f"{PY} {SCRIPTS / script} {args}".strip()}


def plan(verb: str, ws: str | None) -> tuple[int, dict]:
    v = VERBS[verb]
    if v.get("workspace", True) and not ws:
        return 1, {"ok": False, "status": "needs_args", "verb": verb,
                   "needs": [{"arg": "workspace", "question": "Which board workspace?"}]}
    if ws and not fwenv.workspace(ws).is_dir():
        return 2, {"ok": False, "error": f"no workspace {ws}"}
    wsp = str(fwenv.workspace(ws)) if ws else None
    return 0, {"ok": True, "status": "planned", "verb": verb, "workspace": wsp,
               "summary": v["summary"], "doc": str(RECIPES / f"{verb}.md"),
               "steps": [bind(s, wsp) for s in v["steps"]]}


FPGA = re.compile(r"\b(fpga|gateware|verilog|rtl|bitstream|serdes|gearbox|yosys|nextpnr|cocotb|ecp5)\b")


def match(task: str) -> list[str]:
    t = task.lower().strip()
    fpga = bool(FPGA.search(t))
    return [n for n, v in VERBS.items() if v.get("fpga", False) == fpga
            and any(re.search(rx, t) for rx in v["match"])]


def validate() -> list[str]:
    bad = []
    for n, v in VERBS.items():
        if not (RECIPES / f"{n}.md").is_file():
            bad.append(f"{n}: no recipe {n}.md")
        for s in v["steps"]:
            if not s.startswith("agent:") and not (SCRIPTS / s.split()[0]).is_file():
                bad.append(f"{n}: no script {s.split()[0]}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task", help="the user's words")
    g.add_argument("--verb", choices=sorted(VERBS), help="plan this verb directly")
    g.add_argument("--list", action="store_true", help="print the verb table")
    g.add_argument("--validate", action="store_true", help="check every script and recipe exists")
    ap.add_argument("--workspace", help="board workspace (path, or name under boards root)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    if a.list:
        rc, res = 0, {"ok": True, "verbs": {n: v["summary"] for n, v in VERBS.items()}}
    elif a.validate:
        bad = validate()
        rc, res = (1 if bad else 0), {"ok": not bad, "problems": bad}
    elif a.verb:
        rc, res = plan(a.verb, a.workspace)
    else:
        hits = match(a.task)
        if len(hits) == 1:
            rc, res = plan(hits[0], a.workspace)
        elif len(hits) > 1:
            rc, res = 1, {"ok": False, "status": "ambiguous", "candidates": hits,
                          "question": "Which of these is the task? Re-run with --verb."}
        else:
            rc, res = 1, {"ok": False, "status": "unknown", "verbs": sorted(VERBS),
                          "question": "Classify against --list, or ask the user."}
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
