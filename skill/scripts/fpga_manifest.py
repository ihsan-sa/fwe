#!/usr/bin/env python3
"""fpga_manifest.py - write or check firmware/fwe-manifest.json for an FPGA board.

The manifest is what /npie reads to program the board and drive it as an
instrument (reference/fpga.md has the schema, `fwe-fpga-manifest/1`): the
FPGA and its pins from gateware.json's `board`, the timing geometry (with
the clocks the board's PLLs really give), the UART register protocol and
map, the per-channel skew calibration table and the register writes that
load it, the safety behaviour, and the bitstream when one exists. `verified`
is evidence, not derivation: `sim` and `synth` are true only when
build/sim.json and build/build.json passed on the current design
(gateware.design_hash), `bitstream` only when that build went through place
and route with timing met and the bitstream file exists, and `hardware` is
always false because /fwe never touches a bench.

  fpga_manifest.py --workspace PCB-0025-A_pwm-fpga-8ch [--check]

JSON to stdout (or --out): {"ok", "manifest", "stale"?, "board_missing"}.
Exit 0 written (or --check: current), 1 --check found it stale or absent,
2 error (no gateware project).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, gateware  # noqa: E402
from fw_build import version  # noqa: E402

BITSTREAM = "build/pwm8.bit"
TAP_S = 25e-12      # DELAYF's nominal tap (TN-02035); the real one is measured with the skew
_PN = re.compile(r"^(PCB-\d{4}-[A-HJ-NP-Z])_")


def registers(ch: int, n: int) -> list[dict]:
    regs = [{"addr": 0x00, "name": "id", "access": "r", "value": 0xF8},
            {"addr": 0x01, "name": "ctrl", "access": "rw",
             "bits": {"0": "enable (rw): off at once, on at the next period start",
                      "1": "commit (w): load every phase, duty and trim at the next period start",
                      "2": "pending (r): a commit waits for the period start",
                      "3": "taps moving (r): a fine trim is still walking its delay line"}},
            {"addr": 0x02, "name": "steps_per_period", "access": "r", "value": n},
            {"addr": 0x03, "name": "word_bits", "access": "r"},
            {"addr": 0x04, "name": "channels", "access": "r", "value": ch},
            {"addr": 0x05, "name": "fine_taps", "access": "r", "value": gateware.FINE_TAPS}]
    regs += [{"addr": 0x10 + k, "name": f"phase{k}", "access": "rw", "range": [0, n - 1],
              "unit": "step"} for k in range(ch)]
    regs += [{"addr": 0x18 + k, "name": f"duty{k}", "access": "rw", "range": [0, n],
              "unit": "step"} for k in range(ch)]
    regs += [{"addr": 0x20 + k, "name": f"trim_coarse{k}", "access": "rw", "range": [0, n - 1],
              "unit": "step"} for k in range(ch)]
    regs += [{"addr": 0x28 + k, "name": f"trim_fine{k}", "access": "rw",
              "range": [0, gateware.FINE_TAPS - 1], "unit": "tap"} for k in range(ch)]
    return regs


def calibration(cfg: dict, step_s: float) -> dict:
    """The skew trim table gateware.json carries, and the writes that load it."""
    cal = gateware.calibration(cfg)
    table = [{"channel": k, "coarse": c, "fine": f}
             for k, (c, f) in enumerate(zip(cal["coarse"], cal["fine"]))]
    return {"source": cal["source"], "step_s": step_s, "tap_s_nominal": TAP_S,
            "fine_taps": gateware.FINE_TAPS, "table": table,
            "load": [{"addr": a, "value": v} for t in table
                     for a, v in ((0x20 + t["channel"], t["coarse"]), (0x28 + t["channel"], t["fine"]))],
            "then": "write ctrl (0x01) with bit1 set (commit) and bit0 as wanted, then read ctrl "
                    "until bit3 clears: the trim lands with the commit, at a period start",
            "meaning": "channel k is held back by coarse steps plus fine delay taps; every channel "
                       "is trimmed to the latest one, so a table of zeros is uncalibrated",
            "problems": cal["problems"]}


def derive(ws: Path) -> dict:
    fw = ws / "firmware"
    cfg = gateware.load(fw)
    geo = gateware.geometry(cfg)
    b = cfg.get("board") or {}
    m = _PN.match(ws.name)
    ch, n = cfg["channels"], geo["steps_per_period"]
    pins = b.get("pwm_pins") or [None] * ch
    bit = fw / BITSTREAM
    clk = gateware.clocking(cfg)
    step = clk["step_s"] if clk else geo["step_s"]
    built = gateware.recorded_ok(fw, "build") and json.loads(
        (fw / "build" / "build.json").read_text(encoding="utf-8")).get("step") == "bitstream"
    loader = ["openFPGALoader", *(["-b", b["loader"]] if b.get("loader") else []), "{bitstream}"]
    return {
        "schema": "fwe-fpga-manifest/1",
        "board": m.group(1) if m else ws.name,
        "kind": "fpga",
        "design": cfg["design"],
        "version": version(ws, "0.1.0"),
        "fpga": {k: b.get(k) for k in ("model", "vendor", "part", "package", "speed")},
        "clock": {"ref_hz": b.get("ref_clk_hz"), "ref_pin": b.get("ref_clk_pin"),
                  "fabric_hz": clk["sclk_hz"] if clk else geo["fabric_clk_hz"],
                  "edge_hz": clk["eclk_hz"] if clk else None,
                  "f_rf_actual_hz": clk["f_rf_hz"] if clk else None,
                  "f_rf_error_ppm": round(clk["f_rf_ppm"], 2) if clk else None},
        "artifact": {"bitstream": BITSTREAM if bit.is_file() else None,
                     "sha256": hashlib.sha256(bit.read_bytes()).hexdigest() if bit.is_file() else None},
        "program": {"commands": {"openFPGALoader": loader}},
        "geometry": {"f_rf_hz": cfg["f_rf_hz"], "channels": ch, "steps_per_period": n,
                     "word_bits": geo["word_bits"], "step_s": step,
                     "line_rate_bps": clk["line_rate_bps"] if clk else geo["line_rate_bps"]},
        "outputs": [{"channel": k, "pin": pins[k] if k < len(pins) else None,
                     "io_standard": b.get("io_standard"), "io_attrs": b.get("io_attrs") or {},
                     "drives": "the output board's 50 ohm driver, not the load"} for k in range(ch)],
        "uart": {"rx_pin": b.get("uart_rx_pin"), "tx_pin": b.get("uart_tx_pin"),
                 "baud": cfg["uart_baud"], "format": "8N1", "protocol": "fwe-pwm8-reg/1",
                 "note": b.get("uart_note")},
        "protocol": {"write": {"send": ["0x57", "{addr}", "{value}"], "ok": "0x4B", "refused": "0x45"},
                     "read": {"send": ["0x52", "{addr}"], "reply": "{value}", "refused": "0x45"},
                     "unknown_command": "0x3F"},
        "registers": registers(ch, n),
        "calibration": calibration(cfg, step),
        "safety": {"outputs_at_reset": "low", "disable": "immediate",
                   "enable": "next period start", "update": "atomic at the next period start "
                   "after a commit", "range_check": "an out-of-range phase or duty is refused, never clamped"},
        "verified": {"sim": gateware.recorded_ok(fw, "sim"),
                     "synth": gateware.recorded_ok(fw, "build"),
                     "bitstream": built and bit.is_file(), "hardware": False},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--check", action="store_true", help="compare with the manifest on disk, write nothing")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    fw = ws / "firmware"
    if not (fw / "gateware.json").is_file():
        fwenv.emit({"ok": False, "error": f"no gateware project in {fw}: run fpga_scaffold.py"}, a.out)
        return 2
    man = derive(ws)
    path = fw / "fwe-manifest.json"
    res = {"ok": True, "manifest": str(path), "board_missing": gateware.board_missing(gateware.load(fw))}
    if a.check:
        old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        stale = sorted(k for k in man if old is None or old.get(k) != man[k])
        res.update(ok=not stale, stale=stale)
        fwenv.emit(res, a.out)
        return 0 if not stale else 1
    path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    fwenv.emit(res, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
