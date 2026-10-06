#!/usr/bin/env python3
"""fpga_setup.py - check the FPGA toolchain /fwe uses for gateware, and install place and route.

Simulation and synthesis run on chip-flow's `bin/eda` (the IIC-OSIC-TOOLS
tree /vde uses): iverilog, vvp, verilator, yosys and its python with
cocotb. Place and route needs nextpnr-ecp5 and ecppack (prjtrellis), which
that tree does not ship; they are looked up in the user-level OSS CAD Suite
(gateware.tools_home()), then on PATH.

--install downloads the pinned OSS CAD Suite release (RELEASE, checked
against its SHA256) and unpacks it into gateware.tools_home(): user space
only, no root, no package manager, nothing outside the home directory. It
never touches chip-flow's tree, and a suite already there is kept.

  fpga_setup.py [--install]

JSON to stdout (or --out): {"ok", "tools": {name: argv|null}, "cocotb",
"missing", "pnr_missing", "installed"?}. Exit 0 sim, synth and
place-and-route tools all found; 1 only the place-and-route tools are
missing (sim and synth still work); 2 a sim or synth tool is missing, or
--install failed (`error` says why).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

SIM = ("iverilog", "vvp", "verilator", "yosys")
PNR = ("nextpnr-ecp5", "ecppack")
RELEASE = "2026-10-05"
ASSET = f"oss-cad-suite-linux-x64-{RELEASE.replace('-', '')}.tgz"
URL = f"https://github.com/YosysHQ/oss-cad-suite-build/releases/download/{RELEASE}/{ASSET}"
SHA256 = "0c432bb689ba2aaea76d4c38fa6e7b3a81b1123e00d437bfae8c96b292bc6824"   # the release asset digest


def install() -> str | None:
    """Unpack the pinned suite into tools_home(); None when done, else why not."""
    home = gateware.tools_home()
    if (home / "bin" / PNR[0]).is_file():
        return None
    cache = Path.home() / ".cache" / "fwe" / "dl"
    cache.mkdir(parents=True, exist_ok=True)
    tgz = cache / ASSET
    if not tgz.is_file():
        part = tgz.with_suffix(".part")
        with urllib.request.urlopen(URL, timeout=60) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        part.rename(tgz)
    h = hashlib.sha256()
    with tgz.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != SHA256:
        tgz.unlink()
        return f"{ASSET}: sha256 {h.hexdigest()} is not the pinned {SHA256}; deleted it"
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent) as tmp, tarfile.open(tgz) as t:
        t.extractall(tmp, filter="data")
        (Path(tmp) / "oss-cad-suite").rename(home)
    return None


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
    ap.add_argument("--install", action="store_true",
                    help=f"install OSS CAD Suite {RELEASE} in user space when place and route is missing")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    rc, res = check()
    if a.install and res["pnr_missing"]:
        try:
            err = install()
        except OSError as e:
            err = f"{type(e).__name__}: {e}"
        if err:
            fwenv.emit({**res, "ok": False, "error": err}, a.out)
            return 2
        rc, res = check()
        res["installed"] = str(gateware.tools_home())
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
