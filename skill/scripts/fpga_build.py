#!/usr/bin/env python3
"""fpga_build.py - lint and synthesise an FPGA project; place and route once the board is known.

Runs in order, stopping at the first failure:
  1. lint: Verilator -Wall over rtl/*.v, top pwm8_ctrl (width warnings off:
     the core compares narrow registers against wider sums on purpose);
  2. synth: yosys synth_<family> of the board-independent core at
     gateware.json's geometry, giving its cell counts (ECP5 until the board
     says otherwise);
  3. bitstream: not automated yet. It refuses (exit 2) and names what is
     missing first: gateware.json's `board` (filled from the handoff
     README), nextpnr for the family, then the board top and its place and
     route, which the board stage adds (recipes/fpga-build.md).
     --synth-only stops after 2.

  fpga_build.py --workspace PCB-0025-A_pwm-fpga-8ch [--synth-only]

JSON to stdout (or --out): {"ok", "step", "geometry", "cells", "bitstream",
"log_tail"}; also recorded in build/build.json for fpga_manifest.py.
Exit 0 done (with --synth-only: synthesised), 1 lint or synth failed (`step`
says which), 2 error (no project, a tool missing, the board not chosen yet).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

TOP = "pwm8_ctrl"
FAMILIES = {"lattice": "ecp5", "ecp5": "ecp5"}


def tail(text: str, n: int = 30) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def family(cfg: dict) -> str:
    v = ((cfg.get("board") or {}).get("vendor") or "ecp5").lower()
    return next((f for k, f in FAMILIES.items() if k in v), v)


def build(ws: Path, synth_only: bool) -> tuple[int, dict]:
    fw = ws / "firmware"
    if not (fw / "gateware.json").is_file():
        return 2, {"ok": False, "error": f"no gateware project in {fw}: run fpga_scaffold.py"}
    cfg = gateware.load(fw)
    geo = gateware.geometry(cfg)
    if geo["problems"]:
        return 2, {"ok": False, "error": "gateware.json: " + "; ".join(geo["problems"])}
    lint, yosys = gateware.tool("verilator"), gateware.tool("yosys")
    if not lint or not yosys:
        return 2, {"ok": False, "error": "verilator or yosys missing: run fpga_setup.py"}
    rtl = [str(p) for p in gateware.sources(fw, "rtl")]
    params = {"N": geo["steps_per_period"], "W": geo["word_bits"],
              "PW": geo["phase_bits"], "CPB": geo["uart_cpb"]}
    res = {"ok": False, "geometry": {k: v for k, v in geo.items() if k != "problems"},
           "family": family(cfg), "bitstream": None}
    out = fw / "build"
    out.mkdir(exist_ok=True)
    p = subprocess.run([*lint, "--lint-only", "-Wall", "-Wno-DECLFILENAME", "-Wno-WIDTHEXPAND",
                        "-Wno-WIDTHTRUNC", "--top-module", TOP,
                        *[f"-G{k}={v}" for k, v in params.items()], *rtl],
                       cwd=fw, capture_output=True, text=True)
    if p.returncode != 0:
        return 1, {**res, "step": "lint", "log_tail": tail(p.stdout + p.stderr)}
    synth = "synth_ecp5" if res["family"] == "ecp5" else "synth"
    script = (f"read_verilog {' '.join(rtl)}; "
              f"chparam {' '.join(f'-set {k} {v}' for k, v in params.items())} {TOP}; "
              f"{synth} -top {TOP} -json {out / (TOP + '.json')}; tee -o {out / 'synth_stat.txt'} stat")
    p = subprocess.run([*yosys, "-q", "-p", script], cwd=fw, capture_output=True, text=True)
    stat = out / "synth_stat.txt"
    if p.returncode != 0 or not stat.is_file():
        return 1, {**res, "step": "synth", "log_tail": tail(p.stdout + p.stderr)}
    res["cells"] = {m.group(2): int(m.group(1)) for m in
                    re.finditer(r"^\s+(\d+)\s+(\w+)\s*$", stat.read_text(), re.M)
                    if not m.group(2).startswith("$")}
    if synth_only:
        res.update(ok=True, step="synth")
        gateware.record(fw, "build", res)
        return 0, res
    missing = gateware.board_missing(cfg)
    if missing:
        return 2, {**res, "step": "bitstream",
                   "error": "the board is not chosen yet: fill gateware.json `board` from "
                            f"firmware/README.md (missing {', '.join(missing)}), or use --synth-only"}
    pnr = gateware.tool(f"nextpnr-{res['family']}")
    if not pnr:
        return 2, {**res, "step": "bitstream",
                   "error": f"nextpnr-{res['family']} not installed: run fpga_setup.py"}
    return 2, {**res, "step": "bitstream",
               "error": "no board top yet: write it per recipes/fpga-build.md, then add its "
                        "place-and-route here"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--synth-only", action="store_true", help="stop after synthesis")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = build(ws, a.synth_only)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
