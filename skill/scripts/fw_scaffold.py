#!/usr/bin/env python3
"""fw_scaffold.py - start a board's firmware project from an /fwe template.

Copies templates/<family>/ into <workspace>/firmware/, then runs pinmap.py so
gen/board_pins.h and pinmap.json match the board's netlist. A file that is
already in firmware/ is never overwritten: the project is the board's own
once it exists, and a template change reaches it only through a stage edit.
The family comes from the MCU the pin map finds (STM32G4 -> stm32g4).

  fw_scaffold.py --workspace PCB-0018-A_bldc-motor-driver

JSON to stdout (or --out): {"ok", "firmware", "template", "copied", "kept",
"pinmap"}. Exit 0 ok, 1 the pin map has findings, 2 error (no template for
the MCU, no netlist).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

TEMPLATES = fwenv.SKILL / "templates"
FAMILY = {"STM32G4": "stm32g4"}


def run_pinmap(ws: Path, *extra: str) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("pinmap.py")),
                        "--workspace", str(ws), *extra], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return 2, {"ok": False, "error": (p.stderr or p.stdout).strip()[-400:]}


def scaffold(ws: Path) -> tuple[int, dict]:
    rc, pm = run_pinmap(ws)
    if rc == 2:
        return 2, {"ok": False, "error": f"pinmap: {pm.get('error')}"}
    part = pm["mcu"]["part"]
    fam = next((v for k, v in FAMILY.items() if part.startswith(k)), None)
    if not fam or not (TEMPLATES / fam).is_dir():
        return 2, {"ok": False, "error": f"no /fwe template for {part}"}
    src, fw = TEMPLATES / fam, ws / "firmware"
    copied, kept = [], []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        dst = fw / rel
        if dst.exists():
            kept.append(str(rel))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        copied.append(str(rel))
    return rc, {"ok": rc == 0, "firmware": str(fw), "template": fam, "copied": copied,
                "kept": kept, "pinmap": {"findings": pm["findings"], "files": pm["files"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = scaffold(ws)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
