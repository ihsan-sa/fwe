#!/usr/bin/env python3
"""mcu_advice.py - fwe's advice to hwde on an MCU's configuration, before layout.

Reads the board's draft netlist (<workspace>/kicad/<ws>.net, as pinmap.py
does), finds the MCU and checks how the schematic sets it up for the
firmware: debug access (SWDIO and SWCLK on the pins the MCU table gives them,
reaching a header or test pad), reset (NRST reaching the debug header, a
capacitor to GND) and the BOOT0 strap (held low, never pulled up by a part
sharing its pin). Each problem is one advice item hwde can act on while the
board is still being drawn; nothing is guessed, and a pin the table does not
name is not checked.

STM32 boards only for now; an ESP32 board is refused (exit 2).

Writes <workspace>/firmware/mcu-advice.json (schema fwe-mcu-advice/1):
{"schema", "board", "workspace", "netlist", "netlist_sha256", "mcu",
"advice": [{"topic", "severity", "pin", "net", "says", "why"}], "ok"}.
severity is "must" (the board cannot be debugged or boot its firmware as
drawn) or "should". Exit 0 no "must" item, 1 any "must", 2 error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pinmap  # noqa: E402
from fwelib import fwenv  # noqa: E402
from fwelib.netlist import NetlistError, parse_netlist  # noqa: E402
from pinmap import Error, Netlist, short  # noqa: E402

SCHEMA = "fwe-mcu-advice/1"
_HEADER = re.compile(r"^(J|P|CN|TP|X)\d")


def _unconnected(net: str | None) -> bool:
    return net is None or short(net).startswith("unconnected-")


def _on_header(nl: Netlist, net: str, mcu: str) -> bool:
    return any(_HEADER.match(r) for r, _ in nl.refs_on(net) if r != mcu)


def _to_rails(nl: Netlist, net: str, prefix: str) -> list[tuple[str, float]]:
    """(ref, volts) for each 2-pin part with this prefix from net to a known rail."""
    out = []
    for ref, pin in nl.refs_on(net):
        if ref.startswith(prefix) and not ref.startswith(prefix + "N"):
            o = nl.other_net(ref, pin)
            v = nl.volts(o) if o else None
            if v is not None:
                out.append((ref, v))
    return out


def _item(topic, severity, pin, net, says, why) -> dict:
    return {"topic": topic, "severity": severity, "pin": pin,
            "net": None if _unconnected(net) else short(net), "says": says, "why": why}


def debug_advice(nl: Netlist, mcu: str, table: dict, io: dict) -> list[dict]:
    out = []
    for sig in ("SWDIO", "SWCLK"):
        pin = next((p for p, d in table["pins"].items() if d.get("af", {}).get(sig) == 0), None)
        if pin is None:
            continue
        net = io.get(pin)
        if _unconnected(net):
            out.append(_item("debug", "must", pin, net, f"connect {pin} to {sig} on a debug header",
                             f"{pin} is the MCU's only {sig}; without it no probe can flash or debug"))
        elif pinmap.classify(net)[0] != "swd":
            out.append(_item("debug", "must", pin, net,
                             f"give {pin} to {sig} on a debug header and move {short(net)} to another pin",
                             f"{pin} is the MCU's only {sig}; once firmware drives it as {short(net)} "
                             "the probe can no longer attach"))
        elif not _on_header(nl, net, mcu):
            out.append(_item("debug", "should", pin, net, f"bring {short(net)} to a header or test pad",
                             "a probe needs somewhere to land on the bare board"))
    return out


def reset_advice(nl: Netlist, mcu: str, pin: str, net: str | None) -> list[dict]:
    out = []
    if _unconnected(net) or not _on_header(nl, net, mcu):
        out.append(_item("reset", "should", pin, net, "bring NRST to the debug header",
                         "the probe connects under reset when firmware has turned SWD off or sleeps"))
    if _unconnected(net) or not any(v == 0 for _, v in _to_rails(nl, net, "C")):
        out.append(_item("reset", "should", pin, net, "add 100 nF from NRST to GND",
                         "ST's hardware guide (AN5093 for the G4) asks for it against reset glitches"))
    return out


def boot_advice(nl: Netlist, pin: str, net: str | None) -> list[dict]:
    if _unconnected(net):
        return [_item("boot", "should", pin, net, f"pull {pin} (BOOT0) to GND through 10k, with a pad to 3V3",
                      "nothing holds BOOT0 low at reset; the pad keeps the ROM bootloader in reach")]
    v = nl.volts(net)
    if v is not None and v > 0:
        return [_item("boot", "must", pin, net, f"take {pin} (BOOT0) off {short(net)}",
                      "BOOT0 high at reset starts the ROM bootloader, never the firmware")]
    rs = _to_rails(nl, net, "R")
    ups = [r for r, v in rs if v > 0]
    downs = [r for r, v in rs if v == 0]
    if ups and not downs:
        return [_item("boot", "must", pin, net,
                      f"{pin} is BOOT0 at reset and {', '.join(ups)} pulls {short(net)} high; move "
                      f"{short(net)} to another pin or hold {pin} low",
                      "BOOT0 high at reset starts the ROM bootloader, never the firmware")]
    if ups:
        return [_item("boot", "should", pin, net,
                      f"{pin} (BOOT0) is pulled both ways ({', '.join(ups)} up, {', '.join(downs)} down)",
                      "a divider leaves the boot source to resistor tolerances")]
    if not downs and v is None:
        return [_item("boot", "should", pin, net, f"pull {pin} (BOOT0) to GND through 10k",
                      "nothing on the board holds BOOT0 low at reset")]
    return []


def advise(ws: Path, mcu_ref: str | None) -> dict:
    nets = sorted((ws / "kicad").glob("*.net"))
    if len(nets) != 1:
        raise Error(f"expected one netlist in {ws / 'kicad'}, found {len(nets)}")
    netfile = nets[0]
    nl = Netlist(parse_netlist(netfile))
    mcu = pinmap.find_mcu(nl, mcu_ref)
    part = nl.comps[mcu]["value"]
    if part.upper().startswith("ESP32"):
        raise Error(f"{part}: ESP32 advice (boot straps) is not written yet; STM32 boards only")
    fam, table = pinmap.load_mcu_table(part)
    io, reset, boot = {}, None, None
    for num, net in nl.pins[mcu].items():
        func = nl.func[(mcu, num)]
        g = pinmap._GPIO.match(func)
        if g:
            io[g.group(1)] = net
        if "NRST" in func.upper():
            reset = (g.group(1) if g else "NRST", net)
        if "BOOT0" in func.upper():
            boot = (g.group(1) if g else "BOOT0", net)
    advice = debug_advice(nl, mcu, table, io)
    if reset:
        advice += reset_advice(nl, mcu, *reset)
    if boot:
        advice += boot_advice(nl, *boot)
    return {"schema": SCHEMA, "board": ws.name.split("_", 1)[0], "workspace": ws.name,
            "netlist": f"kicad/{netfile.name}",
            "netlist_sha256": hashlib.sha256(netfile.read_bytes()).hexdigest(),
            "mcu": {"ref": mcu, "part": part, "table": fam},
            "advice": advice, "ok": not any(a["severity"] == "must" for a in advice)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--mcu", help="MCU refdes when the netlist has more than one STM32 or ESP32")
    ap.add_argument("--fw-dir", default="firmware", help="firmware dir, relative to the workspace")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    try:
        if Path(a.fw_dir).is_absolute() or ".." in Path(a.fw_dir).parts:
            raise Error(f"--fw-dir {a.fw_dir} must be a path inside the workspace")
        res = advise(ws, a.mcu)
        dest = ws / a.fw_dir / "mcu-advice.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        rc = 0 if res["ok"] else 1
    except (Error, NetlistError, OSError, ValueError) as exc:
        res, rc = {"ok": False, "error": str(exc)}, 2
    text = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
