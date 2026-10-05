#!/usr/bin/env python3
"""fpga_scaffold.py - start a board's gateware project from the /fwe FPGA template.

Copies templates/fpga/ into <workspace>/firmware/. A file already there is
never overwritten (the boards seat's handoff README, a gateware.json the
board stage filled in, an edited core). An off-the-shelf dev board has no
netlist in the workspace, so unlike fw_scaffold.py nothing is derived here:
the board stage fills gateware.json's `board` from firmware/README.md.

  fpga_scaffold.py --workspace PCB-0025-A_pwm-fpga-8ch

JSON to stdout (or --out): {"ok", "firmware", "template", "copied", "kept",
"board_missing"}. Exit 0 ok, 2 error (no workspace).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

TEMPLATE = fwenv.SKILL / "templates" / "fpga"


def scaffold(ws: Path) -> tuple[int, dict]:
    fw = ws / "firmware"
    copied, kept = [], []
    for f in sorted(p for p in TEMPLATE.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = f.relative_to(TEMPLATE)
        dst = fw / rel
        if dst.exists():
            kept.append(str(rel))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        copied.append(str(rel))
    return 0, {"ok": True, "firmware": str(fw), "template": "fpga", "copied": copied,
               "kept": kept, "board_missing": gateware.board_missing(gateware.load(fw))}


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
