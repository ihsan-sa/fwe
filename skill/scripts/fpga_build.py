#!/usr/bin/env python3
"""fpga_build.py - lint and synthesise an FPGA project; place and route once the board is known.

Runs in order, stopping at the first failure:
  1. lint: Verilator -Wall over rtl/*.v, top pwm8_ctrl (width warnings off:
     the core compares narrow registers against wider sums on purpose);
  2. synth: yosys synth_<family> of the board-independent core at
     gateware.json's geometry, giving its cell counts (ECP5 until the board
     says otherwise);
  3. bitstream (ECP5): refuses (exit 2) and names what is missing first,
     gateware.json's `board` (fpga_scaffold.py --board, or filled from the
     handoff README), nextpnr-ecp5 and ecppack (fpga_setup.py --install),
     or `board.pll`. Then yosys synthesises the board top
     vendor/ecp5/pwm8_top.v with the geometry, the PLL divides and CPB =
     core clock / baud; nextpnr places and routes it against build/pnr/pwm8.lpf
     (pins, I/O attributes and the core clock, written from `board`);
     every pin must get its output delay (DELAYF) and every clock must
     meet its constraint, else exit 1 with `step` "pnr" or "timing" and
     the slack; ecppack then writes build/pwm8.bit.
     --synth-only stops after 2.

  fpga_build.py --workspace PCB-0025-A_pwm-fpga-8ch [--synth-only]

JSON to stdout (or --out): {"ok", "step", "geometry", "cells", "bitstream",
"clocking", "timing", "utilization", "output_delays", "log_tail"}; recorded
in build/build.json for fpga_manifest.py when it succeeds. Exit 0 done
(with --synth-only: synthesised), 1 lint, synth, place and route or timing
failed (`step` says which), 2 error (no project, a tool missing, the board
not chosen yet).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402

TOP = "pwm8_ctrl"
BOARD_TOP = "pwm8_top"
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
    pack = gateware.tool("ecppack")
    if res["family"] != "ecp5" or not pack:
        return 2, {**res, "step": "bitstream",
                   "error": "ecppack not installed: run fpga_setup.py --install"
                   if pack is None else f"no place and route for {res['family']} yet"}
    clk = gateware.clocking(cfg)
    if clk is None or clk["problems"]:
        return 2, {**res, "step": "bitstream", "error": "board.pll: " + (
            "; ".join(clk["problems"]) if clk else "missing (the PLL divides from the handoff README)")}
    res["clocking"] = {k: v for k, v in clk.items() if k != "problems"}
    return place_and_route(fw, cfg, res, [*rtl, *map(str, gateware.sources(fw, f"vendor/{res['family']}"))],
                           yosys, pnr, pack, clk)


def lpf(cfg: dict, sclk_hz: float) -> str:
    """Pin constraints from gateware.json's `board`, and the clocks to time."""
    b = cfg["board"]
    attrs = " ".join(f"{k}={v}" for k, v in (b.get("io_attrs") or {}).items())
    io = f"IO_TYPE={b['io_standard']}"
    lines = [f'LOCATE COMP "clk_ref" SITE "{b["ref_clk_pin"]}";',
             f'IOBUF PORT "clk_ref" {io};',
             f'FREQUENCY PORT "clk_ref" {b["ref_clk_hz"] / 1e6:.6f} MHZ;',
             f'FREQUENCY NET "sclk" {sclk_hz / 1e6:.6f} MHZ;',
             f'LOCATE COMP "uart_rx" SITE "{b["uart_rx_pin"]}";',
             f'IOBUF PORT "uart_rx" {io} PULLMODE=UP;',
             f'LOCATE COMP "uart_tx" SITE "{b["uart_tx_pin"]}";',
             f'IOBUF PORT "uart_tx" {io};']
    for k, pin in enumerate(b["pwm_pins"]):
        lines += [f'LOCATE COMP "pwm[{k}]" SITE "{pin}";', f'IOBUF PORT "pwm[{k}]" {io} {attrs};']
    return "\n".join(lines) + "\n"


def place_and_route(fw: Path, cfg: dict, res: dict, srcs: list[str], yosys, pnr, pack,
                    clk: dict) -> tuple[int, dict]:
    """Synthesise the board top, place and route it, check timing, pack the bitstream."""
    geo, b = gateware.geometry(cfg), cfg["board"]
    out = fw / "build" / "pnr"
    out.mkdir(parents=True, exist_ok=True)
    params = {"N": geo["steps_per_period"], "W": geo["word_bits"], "PW": geo["phase_bits"],
              "CPB": clk["uart_cpb"]}
    for i, p in enumerate(b["pll"], 1):
        params.update({f"P{i}_CLKI": p["CLKI_DIV"], f"P{i}_FB": p["CLKFB_DIV"],
                       f"P{i}_OP": p["CLKOP_DIV"], f"P{i}_OS": p["CLKOS_DIV"]})
    net = out / "pwm8_top.json"
    script = (f"read_verilog {' '.join(srcs)}; "
              f"chparam {' '.join(f'-set {k} {v}' for k, v in params.items())} {BOARD_TOP}; "
              f"synth_ecp5 -top {BOARD_TOP} -json {net}")
    p = subprocess.run([*yosys, "-q", "-l", str(out / "yosys.log"), "-p", script], cwd=fw,
                       capture_output=True, text=True)
    if p.returncode != 0:
        return 1, {**res, "step": "synth_top", "log_tail": tail(p.stdout + p.stderr)}
    (out / "pwm8.lpf").write_text(lpf(cfg, clk["sclk_hz"]), encoding="ascii")
    report, cfgtxt = out / "report.json", out / "pwm8.config"
    p = subprocess.run([*pnr, *b.get("nextpnr_args", []), "--json", str(net),
                        "--lpf", str(out / "pwm8.lpf"), "--textcfg", str(cfgtxt),
                        "--report", str(report), "--timing-allow-fail", "--seed", "1",
                        "--log", str(out / "nextpnr.log")],
                       cwd=fw, capture_output=True, text=True)
    if p.returncode != 0 or not report.is_file():
        return 1, {**res, "step": "pnr", "log_tail": tail(p.stdout + p.stderr)}
    rep = json.loads(report.read_text())
    fmax = {c: {"achieved_mhz": round(v["achieved"], 2), "constraint_mhz": round(v["constraint"], 2)}
            for c, v in rep.get("fmax", {}).items()}
    res["timing"] = fmax
    res["utilization"] = {k: v for k, v in rep.get("utilization", {}).items() if v.get("used")}
    # nextpnr folds each DELAYF into its pin's IOLOGIC: count the output delays it enabled
    res["output_delays"] = cfgtxt.read_text().count("DELAY.OUTDEL ENABLED")
    if res["output_delays"] != cfg["channels"]:
        return 1, {**res, "step": "pnr", "error": f"{res['output_delays']} of {cfg['channels']} "
                   "pins got their output delay (DELAYF): the fine skew trim would not reach them"}
    sclk = [v for c, v in fmax.items() if abs(v["constraint_mhz"] - clk["sclk_hz"] / 1e6) < 0.1]
    if not sclk:
        return 1, {**res, "step": "timing", "error": "nextpnr reported no clock at the core clock: "
                   "the sclk constraint did not reach the netlist"}
    late = {c: v for c, v in fmax.items() if v["achieved_mhz"] < v["constraint_mhz"]}
    if late:
        return 1, {**res, "step": "timing", "error": "timing not met: " + ", ".join(
            f"{c} {v['achieved_mhz']} of {v['constraint_mhz']} MHz" for c, v in late.items())}
    bit = fw / "build" / "pwm8.bit"
    p = subprocess.run([*pack, str(cfgtxt), str(bit)], cwd=fw, capture_output=True, text=True)
    if p.returncode != 0 or not bit.is_file():
        return 1, {**res, "step": "pack", "log_tail": tail(p.stdout + p.stderr)}
    res.update(ok=True, step="bitstream", bitstream="build/pwm8.bit")
    gateware.record(fw, "build", res)
    return 0, res


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
