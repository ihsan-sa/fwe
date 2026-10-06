#!/usr/bin/env python3
"""fpga_scaffold.py - start a board's gateware project from the /fwe FPGA template.

Copies templates/fpga/ into <workspace>/firmware/. A file already there is
never overwritten (the boards seat's handoff README, a gateware.json the
board stage filled in, an edited core). An off-the-shelf dev board has no
netlist in the workspace, so unlike fw_scaffold.py nothing is derived here:
the board stage fills gateware.json's `board` from firmware/README.md.

--board NAME fills gateware.json's `board` and geometry from a known dev
board's profile, templates/fpga-boards/NAME.json (written from that board's
handoff README), when gateware.json was just copied or its `board.part` is
still empty; a board already filled in is kept.

  fpga_scaffold.py --workspace PCB-0025-A_pwm-fpga-8ch [--board lfe5um5g-85f-evn]

JSON to stdout (or --out): {"ok", "firmware", "template", "copied", "kept",
"board", "board_missing"}. Exit 0 ok, 2 error (no workspace, an unknown board).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

TEMPLATE = fwenv.SKILL / "templates" / "fpga"
BOARDS = fwenv.SKILL / "templates" / "fpga-boards"


def scaffold(ws: Path, board: str | None = None) -> tuple[int, dict]:
    fw = ws / "firmware"
    prof = BOARDS / f"{board}.json" if board else None
    if prof and not prof.is_file():
        known = sorted(p.stem for p in BOARDS.glob("*.json"))
        return 2, {"ok": False, "error": f"no board profile {board!r}; known: {', '.join(known)}"}
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
    filled = None
    cfg = gateware.load(fw)
    if prof and ("gateware.json" in copied or not (cfg.get("board") or {}).get("part")):
        pf = json.loads(prof.read_text(encoding="utf-8"))
        cfg.update(pf["geometry"])
        cfg["board"] = {**(cfg.get("board") or {}), **pf["board"]}
        (fw / "gateware.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        filled = pf["name"]
    return 0, {"ok": True, "firmware": str(fw), "template": "fpga", "copied": copied,
               "kept": kept, "board": filled, "board_missing": gateware.board_missing(cfg)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--board", help="fill gateware.json from templates/fpga-boards/BOARD.json")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = scaffold(ws, a.board)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
