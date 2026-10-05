#!/usr/bin/env python3
"""fpga_setup.py - check the FPGA toolchain /fwe uses for gateware.

Simulation and synthesis run on chip-flow's `bin/eda` (the IIC-OSIC-TOOLS
tree /vde uses): iverilog, vvp, verilator, yosys and its python with
cocotb. Place and route needs nextpnr-ecp5 and ecppack (prjtrellis), which
that tree does not ship; they are looked up on PATH. Nothing is installed
here: a missing tool is a finding, and installing one outside user space is
a question for the owner (SKILL.md rule 4).

  fpga_setup.py

JSON to stdout (or --out): {"ok", "tools": {name: argv|null}, "cocotb",
"missing", "pnr_missing"}. Exit 0 sim, synth and place-and-route tools all
found; 1 only the place-and-route tools are missing (sim and synth still
work); 2 a sim or synth tool is missing.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

SIM = ("iverilog", "vvp", "verilator", "yosys")
PNR = ("nextpnr-ecp5", "ecppack")


def check() -> tuple[int, dict]:
    tools = {t: gateware.tool(t) for t in SIM + PNR}
    cocotb = None
    if gateware.eda().is_file():
        p = subprocess.run([str(gateware.eda()), "python", "-c",
                            "import cocotb, cocotb_tools; print(cocotb.__version__)"],
                           capture_output=True, text=True)
        cocotb = (p.stdout.strip() or None) if p.returncode == 0 else None
    missing = [t for t in SIM if not tools[t]] + ([] if cocotb else ["cocotb"])
    pnr = [t for t in PNR if not tools[t]]
    rc = 2 if missing else (1 if pnr else 0)
    return rc, {"ok": rc == 0, "eda": str(gateware.eda()), "tools": tools, "cocotb": cocotb,
                "missing": missing, "pnr_missing": pnr}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    rc, res = check()
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
