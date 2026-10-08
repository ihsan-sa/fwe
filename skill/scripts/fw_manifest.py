#!/usr/bin/env python3
"""fw_manifest.py - write or check firmware/fwe-manifest.json, /npie's interface.

The manifest (reference/manifest.md, schema fwe-manifest/1) is derived, never
hand-written: connectors from the board's netlist, the command list from the
console's dispatch in src/console.c (with each reply's top-level keys; a
command's args and safe flag come from a `/* fwe-cmd args="..." safe=yes|no */`
comment on its dispatch line, else from the KNOWN table; a command in neither
is an error, so every command in the manifest carries its arguments),
the safety limits from config/fw_config.h (the boost template's set when a
pin role starts "hrtim_", plus its `pwm` outputs and comparator `trips` from
the pin map's fault routes),
the version and stage from the last build's CMake cache, and the artifacts'
sha256 from firmware/build/. Run it after fw_build.py.

  fw_manifest.py --workspace PCB-0018-A_bldc-motor-driver [--sim renode]
  fw_manifest.py --workspace <board> --check

--check regenerates in memory and compares with the file on disk (the
`verified` block is not compared: it records evidence, not a derivation).
`verified.host_tests` is true only when fw_test.py passes now; `verified.sim`
names the simulator a smoke test passed in (--sim), else null; `hardware` is
always false, because /fwe never touches a bench.

JSON to stdout (or --out): {"ok", "path", "manifest"} or, with --check,
{"ok", "stale": [keys that differ]}. Exit 0 written / up to date, 1 stale or
missing (--check) or no build to describe, 2 error (including a console
command with no declared args).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402
import pinmap  # noqa: E402
from fw_test import run_tests  # noqa: E402

SCHEMA = "fwe-manifest/1"
NAME = "fwe-manifest.json"
# manifest.md: a command is `safe: false` when it can energise the bridge.
# `arm` turns every low side on (bootstrap charge), `duty` drives the phases.
# A command neither declared (fwe-cmd, below) nor in this table is refused
# (Undeclared): /npie needs every command's arguments.
KNOWN = {
    "version": ("", True), "status": ("", True), "selftest": ("", True),
    "adc": ("", True), "offsets": ("", True), "led": ("<status|fault> <on|off|auto>", True),
    "arm": ("", False), "disarm": ("", True), "duty": ("<a> <b> <c>", False),
    "clear": ("", True), "reset": ("", True),
}
HOOKS = [("version", r'^OK \{"board":"{board}"'), ("status", "^OK "),
         ("selftest", "^OK "), ("adc", "^OK ")]
LIMITS = {"i_trip_a": "I_TRIP_A", "i_limit_a": "I_LIMIT_A", "vbus_ov_v": "VBUS_OV_V",
          "vbus_uv_v": "VBUS_UV_V", "max_duty": "MAX_DUTY", "pwm_hz": "PWM_FREQ_HZ",
          "baud": "UART_BAUD"}
# The HRTIM boost template (a pin role starting "hrtim_", as fw_scaffold.py
# picks it). vbus_* stay the input-supply limits, as /npie reads them on the
# motor boards; the output side gets its own keys.
BOOST_LIMITS = {"i_trip_a": "I_TRIP_A", "i_limit_a": "I_LIMIT_A", "vbus_ov_v": "VIN_OV_V",
                "vbus_uv_v": "VIN_UV_V", "vout_target_v": "VOUT_TARGET_V",
                "vout_ov_v": "VOUT_OV_V", "max_duty": "D_MAX", "pwm_hz": "PWM_FREQ_HZ",
                "dead_time_ns": "DEADTIME_NS", "baud": "UART_BAUD"}
INTS = ("baud", "pwm_hz", "dead_time_ns")
# A hardware trip's threshold: the safety key it is set from, and its unit.
TRIP_LIMIT = {"ovp": ("vout_ov_v", "V"), "ocp": ("i_trip_a", "A")}


class Missing(Exception):
    pass


class Undeclared(Exception):
    """A console command has neither a fwe-cmd declaration nor a KNOWN entry."""


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def config(fw: Path, limits: dict) -> dict:
    text = (fw / "config" / "fw_config.h").read_text(encoding="utf-8")
    out = {}
    for key, macro in limits.items():
        m = re.search(rf"^#define\s+{macro}\s+([0-9.]+)[uf]?\b", text, re.M)
        if not m:
            raise Missing(f"config/fw_config.h has no {macro}")
        out[key] = int(m.group(1)) if key in INTS else float(m.group(1))
    return out


def reply_fields(src: str, func: str) -> list[str]:
    """Top-level keys of a command's OK object: the o_k*/o_obj keys in its
    handler, skipping those nested inside an o_obj(...) .. o_close() block."""
    m = re.search(rf"^static void {func}\([^)]*\)\s*\{{(.*?)^\}}", src, re.M | re.S)
    if not m:
        return []
    keys, depth = [], 0
    for call, key in re.findall(r'\b(o_obj|o_close|o_k\w*)\(\s*"?([a-z_0-9]*)', m.group(1)):
        if call == "o_close":
            depth -= 1
            continue
        if depth == 0 and key not in keys:
            keys.append(key)
        if call == "o_obj":
            depth += 1
    return keys


# A stage declares a command it adds on its dispatch line, and the declaration
# wins over KNOWN:
#   else if (streq(c, "six")) cmd_six(argc, argv);  /* fwe-cmd args="<duty 0..1> <fwd|rev> | stop" safe=no */
DISPATCH = re.compile(r'streq\(c,\s*"([a-z_]+)"\)\)\s*(\w+)\([^\n]*?'
                      r'(?:/\*\s*fwe-cmd\s+args="([^"]*)"\s+safe=(yes|no)\s*\*/)?[ \t]*$', re.M)


def commands(fw: Path) -> list[dict]:
    src = (fw / "src" / "console.c").read_text(encoding="utf-8")
    found = DISPATCH.findall(src)
    if not found:
        raise Missing("src/console.c has no streq(c, \"...\") dispatch")
    bare = [n for n, _, _, safe in found if not safe and n not in KNOWN]
    if bare:
        raise Undeclared(f"src/console.c: command(s) {', '.join(bare)} have no declared args; "
                         'add /* fwe-cmd args="..." safe=yes|no */ to each dispatch line')
    out = []
    for n, f, args, safe in found:
        known = (args, safe == "yes") if safe else KNOWN[n]
        out.append({"name": n, "args": known[0], "reply": "OK {json} | ERR <code> <text>",
                    "reply_fields": reply_fields(src, f), "safe": known[1]})
    return out


def cache(build: Path) -> dict:
    p = build / "CMakeCache.txt"
    if not p.is_file():
        raise Missing("no firmware/build/CMakeCache.txt: run fw_build.py")
    kv = dict(re.findall(r"^(FWE_VERSION|FWE_STAGE):\w+=(.*)$", p.read_text(encoding="utf-8"), re.M))
    return {"version": kv.get("FWE_VERSION", "?"), "stage": kv.get("FWE_STAGE", "?")}


def connector(nl: pinmap.Netlist, mcu: str, net: str) -> tuple[str | None, str | None]:
    """The J* connector and its pin on a net the MCU drives (short name),
    directly or through one series resistor (PCB-0018-A: R701 to J701)."""
    full = next((n for n in nl.nets if pinmap.short(n) == net), None)
    nets = [full] if full else []
    for ref, pin in nl.refs_on(full) if full else []:
        if ref[0] == "R" and (o := nl.other_net(ref, pin)):
            nets.append(o)
    for n in nets:
        for ref, pin in nl.refs_on(n):
            if ref != mcu and ref.startswith("J"):
                return ref, pin
    return None, None


def hrtim(pm: dict, cfg: dict) -> dict:
    """The boost's PWM outputs and its comparator -> HRTIM fault trips, for
    /npie to scope the switching and provoke each trip. A trip forces both
    outputs inactive in hardware and latches until `clear`; the firmware
    reports it as an EVT whose "new" list names `<trip>_hw`."""
    outs = [{"pin": p["pin"], "net": p["net"], "role": p["role"]}
            for p in pm["pins"] if p["role"].startswith("hrtim_")]
    trips = []
    for r in pm.get("fault_routes", []):
        key, unit = TRIP_LIMIT.get(r["trip"], (None, None))
        if key is None:
            raise pinmap.Error(f"fault route {r['trip']} has no threshold key in TRIP_LIMIT")
        trips.append({"name": r["trip"], "kind": "hardware", "sense_net": r["net"],
                      "pin": r["pin"], "comparator": r["comp"], "fault_input": r["fault"],
                      "threshold": cfg[key], "unit": unit, "outputs": "inactive",
                      "latched": True, "clear": "clear",
                      "evt_regex": rf'^EVT {{"trip":{{"new":\[[^]]*"{r["trip"]}_hw"'})
    pwm = {"timer": "HRTIM Timer A", "outputs": outs, "freq_hz": cfg["pwm_hz"],
           "dead_time_ns": cfg["dead_time_ns"], "max_duty": cfg["max_duty"],
           "safe_state": "both outputs low"}
    return {"pwm": pwm, "trips": trips}


def derive(ws: Path) -> dict:
    fw = ws / "firmware"
    pm = pinmap.build(ws, None)
    nl = pinmap.Netlist(pinmap.parse_netlist(ws / pm["netlist"]))
    mcu = pm["mcu"]["ref"]
    by_role = {p["role"]: p for p in pm["pins"]}
    swd = next((p for p in pm["pins"] if p["role"] == "swd"), None)
    swd_j = connector(nl, mcu, swd["net"])[0] if swd else None
    tx, rx = by_role.get("uart_tx"), by_role.get("uart_rx")
    tx_j, tx_pin = connector(nl, mcu, tx["net"]) if tx else (None, None)
    rx_pin = connector(nl, mcu, rx["net"])[1] if rx else None
    supply = sorted(r for r, fn in pm["power_pins"].items() if "VDD" in fn)
    build = fw / "build"
    arts = {n: build / f"fw.{n}" for n in ("elf", "bin", "hex")}
    if not all(p.is_file() for p in arts.values()):
        raise Missing("no firmware/build/fw.{elf,bin,hex}: run fw_build.py")
    boost = any(p["role"].startswith("hrtim_") for p in pm["pins"])
    cfg, bc = config(fw, BOOST_LIMITS if boost else LIMITS), cache(build)
    board = pm["board"]
    man = {
        "schema": SCHEMA, "board": board,
        "mcu": {"part": pm["mcu"]["part"], "core": "cortex-m4", "flash_base": "0x08000000"},
        "stage": bc["stage"], "version": bc["version"],
        "artifact": {**{n: f"build/fw.{n}" for n in arts},
                     "sha256": {n: sha256(p) for n, p in arts.items()}},
        "flash": {"interface": "swd", "connector": swd_j, "commands": {
            "probe-rs": ["probe-rs", "download", "--chip", pm["mcu"]["part"][:11] + "Tx", "{elf}"],
            "openocd": ["openocd", "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                        "-c", "program {elf} verify reset exit"]}},
        "uart": {"connector": tx_j, "tx_pin": tx_pin, "rx_pin": rx_pin, "baud": cfg["baud"],
                 "format": "8N1", "levels": "3V3", "banner_regex": f"^fwe {board} "},
        "commands": commands(fw),
        "test_hooks": [{"name": n, "send": n, "expect": e.replace("{board}", board),
                        "timeout_s": 5, "needs": supply} for n, e in HOOKS],
        "safety": {"pwm_at_reset": "off", "fault_clear": "clear",
                   **{k: v for k, v in cfg.items() if k != "baud"}},
    }
    if boost:
        man.update(hrtim(pm, cfg))
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--check", action="store_true", help="compare with the file on disk, write nothing")
    ap.add_argument("--sim", help="simulator a smoke test passed in (renode), recorded under verified")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    path = ws / "firmware" / NAME
    try:
        if not ws.is_dir():
            raise pinmap.Error(f"no workspace {ws}")
        man = derive(ws)
    except Missing as e:
        fwenv.emit({"ok": False, "error": str(e)}, a.out)
        return 1
    except (Undeclared, pinmap.Error, pinmap.NetlistError, OSError, KeyError) as e:
        fwenv.emit({"ok": False, "error": str(e)}, a.out)
        return 2
    if a.check:
        if not path.is_file():
            fwenv.emit({"ok": False, "stale": ["<missing>"], "path": str(path)}, a.out)
            return 1
        disk = json.loads(path.read_text(encoding="utf-8"))
        stale = sorted(k for k in (set(man) | set(disk)) - {"verified"} if man.get(k) != disk.get(k))
        fwenv.emit({"ok": not stale, "stale": stale, "path": str(path)}, a.out)
        return 1 if stale else 0
    trc, _ = run_tests(ws / "firmware", [], 60.0)
    man["verified"] = {"build": True, "host_tests": trc == 0, "sim": a.sim, "hardware": False}
    path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    fwenv.emit({"ok": True, "path": str(path), "manifest": man}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
