#!/usr/bin/env python3
"""fpga_sim.py - run an FPGA project's cocotb bench over Icarus.

Reuses /vde's simulation (chip-flow engine/lib/cocotblib.py: run_cocotb and
parse_results_xml) rather than a copy of it, so it needs cocotb: run under
chip-flow's `bin/eda python`, which it runs itself under when the
current python has no cocotb. Sources are firmware/rtl/*.v and
firmware/tb/*.v (never vendor/: the bench is board-independent), headed by a
generated build/sim/gw_defs.v that sets the GW_* macros from gateware.json
with a short UART bit time. The top is tb/tb_<design>.v and the tests every
tb/test_*.py. The result is also recorded in build/sim.json, which
fpga_manifest.py reads.

  fpga_sim.py --workspace PCB-0025-A_pwm-fpga-8ch [--timeout 600]

JSON to stdout (or --out): {"ok", "tests": {name: {passed, message}},
"failed", "geometry", "log"}. Exit 0 every test passed, 1 a test failed or
none ran, 2 error (no project, no cocotb/eda, the build did not compile).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402


def defs(geo: dict) -> str:
    return "".join(f"`define GW_{k} {v}\n" for k, v in (
        ("N", geo["steps_per_period"]), ("W", geo["word_bits"]),
        ("PW", geo["phase_bits"]), ("CPB", gateware.SIM_CPB)))


def simulate(ws: Path, timeout: float) -> tuple[int, dict]:
    fw = ws / "firmware"
    if not (fw / "gateware.json").is_file():
        return 2, {"ok": False, "error": f"no gateware project in {fw}: run fpga_scaffold.py"}
    cfg = gateware.load(fw)
    geo = gateware.geometry(cfg)
    if geo["problems"]:
        return 2, {"ok": False, "error": "gateware.json: " + "; ".join(geo["problems"])}
    sys.path.insert(0, str(gateware.chip_flow() / "engine" / "lib"))
    import cocotblib
    top = f"tb_{cfg['design']}"
    tb = fw / "tb"
    if not (tb / f"{top}.v").is_file():
        return 2, {"ok": False, "error": f"no bench top tb/{top}.v"}
    mods = cocotblib.test_modules(tb)
    if not mods:
        return 1, {"ok": False, "error": "no tb/test_*.py: nothing ran"}
    out = fw / "build" / "sim"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gw_defs.v").write_text(defs(geo), encoding="ascii")
    srcs = [out / "gw_defs.v", *gateware.sources(fw, "rtl", "tb")]
    xml = out / "results.xml"
    xml.unlink(missing_ok=True)
    try:
        cocotblib.run_cocotb(out, tb, srcs, top, mods, xml, timeout_s=timeout)
    except Exception as e:  # noqa: BLE001 - the build or the runner failed: not a result
        return 2, {"ok": False, "error": f"{type(e).__name__}: {e}", "log": str(out / "sim.log")}
    if not xml.is_file():
        return 2, {"ok": False, "error": "no results.xml: the bench did not build",
                   "log": str(out / "sim.log")}
    tests = {n: {"passed": r["passed"], "message": r.get("message")}
             for n, r in cocotblib.parse_results_xml(xml).items()}
    failed = sorted(n for n, r in tests.items() if not r["passed"])
    ok = bool(tests) and not failed
    res = {"ok": ok, "tests": tests, "failed": failed,
           "geometry": {k: v for k, v in geo.items() if k != "problems"},
           "log": str(out / "sim.log")}
    gateware.record(fw, "sim", res)
    return (0 if ok else 1), res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--timeout", type=float, default=600, help="wall-clock seconds for build + run")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    try:
        import cocotb  # noqa: F401
    except ImportError:
        if os.environ.get("FWE_IN_EDA") or not gateware.eda().is_file():
            fwenv.emit({"ok": False, "error": "cocotb not found: needs chip-flow's bin/eda"
                        f" ({gateware.eda()})"}, a.out)
            return 2
        return subprocess.run([str(gateware.eda()), "python", __file__,
                               *(argv if argv is not None else sys.argv[1:])],
                              env={**os.environ, "FWE_IN_EDA": "1"}).returncode
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = simulate(ws, a.timeout)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
