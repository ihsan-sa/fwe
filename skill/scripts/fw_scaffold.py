#!/usr/bin/env python3
"""fw_scaffold.py - start a board's firmware project from an /fwe template.

Copies templates/<family>/ into <workspace>/firmware/, then runs pinmap.py so
gen/board_pins.h and pinmap.json match the board's netlist. A file that is
already in firmware/ is never overwritten: the project is the board's own
once it exists, and a template change reaches it only through a stage edit.
The template comes from the MCU the pin map finds and the pins it drives:
an STM32G4 with any pin role starting "hrtim_" (a gate on the high-resolution
timer) gets stm32g474-boost, any other STM32G4 gets stm32g4.

An ESP32 gets the esp32 template, which is our components only: upstream
squeezelite-esp32 is cloned at the lock's pinned commit into
firmware/upstream (fwelib/upstream.py) and our components/fwe_* are linked
into it. An existing clone at another commit is left alone and reported
unless --update is given. No fork and no new remote is ever made.

  fw_scaffold.py --workspace PCB-0018-A_bldc-motor-driver
  fw_scaffold.py --workspace PCB-0029-A_hifi-lite [--update] [--no-fetch]

JSON to stdout (or --out): {"ok", "firmware", "template", "copied", "kept",
"pinmap"}, plus "upstream" and "linked" on an ESP32. Exit 0 ok, 1 the pin
map has findings or the upstream clone is at another commit, 2 error (no
template for the MCU, no netlist, the clone failed).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, squeezelite, upstream  # noqa: E402

TEMPLATES = fwenv.SKILL / "templates"
FAMILY = {"STM32G4": "stm32g4", "ESP32": "esp32"}
# family -> (role prefix, template) checked before the family default
VARIANT = {"stm32g4": ("hrtim_", "stm32g474-boost")}


def run_pinmap(ws: Path, *extra: str) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("pinmap.py")),
                        "--workspace", str(ws), *extra], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return 2, {"ok": False, "error": (p.stderr or p.stdout).strip()[-400:]}


def scaffold(ws: Path, update: bool = False, fetch: bool = True) -> tuple[int, dict]:
    rc, pm = run_pinmap(ws)
    if rc == 2:
        return 2, {"ok": False, "error": f"pinmap: {pm.get('error')}"}
    part = pm["mcu"]["part"]
    fam = next((v for k, v in FAMILY.items() if part.startswith(k)), None)
    if fam == "esp32" and squeezelite.later_series(part):
        fam = None                      # the esp32 template is the classic ESP32's
    var = VARIANT.get(fam)
    if var and any(str(p.get("role", "")).startswith(var[0]) for p in pm.get("pins", [])):
        fam = var[1]
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
    res = {"firmware": str(fw), "template": fam, "copied": copied,
           "kept": kept, "pinmap": {"findings": pm["findings"], "files": pm["files"]}}
    if fam == "esp32" and fetch:
        u = upstream.entry()
        up = upstream.fetch(fw / "upstream", u["repo"], u["commit"], update)
        res["upstream"] = up
        if "error" in up:
            return 2, {"ok": False, "error": up["error"], **res}
        if up["ok"]:
            try:
                res["linked"] = upstream.link_components(fw)
            except ValueError as e:
                return 2, {"ok": False, "error": str(e), **res}
        else:
            rc = 1
    return rc, {"ok": rc == 0, **res}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--update", action="store_true",
                    help="ESP32: check the upstream clone out at the lock's commit if it is elsewhere")
    ap.add_argument("--no-fetch", action="store_true", help="ESP32: copy the template only, no upstream clone")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = scaffold(ws, a.update, not a.no_fetch)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
