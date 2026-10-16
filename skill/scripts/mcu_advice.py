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

On a classic ESP32 module board it checks what the ROM flash and the boot
need instead (the ESP32 datasheet's strapping table, Espressif's hardware
design guidelines): GPIO0 not held low and reachable for download mode,
GPIO2 not held high, GPIO12 (MTDI) not held high, GPIO15 (MTDO) not held low,
EN pulled up with its RC delay, and UART0 (GPIO1, GPIO3) reaching a header or
a USB-UART bridge. An ESP32-C3/S3 is refused (exit 2), as in pinmap.py.

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
from fwelib import fwenv, squeezelite  # noqa: E402
from fwelib.netlist import NetlistError, parse_netlist  # noqa: E402
from pinmap import Error, Netlist, short  # noqa: E402

SCHEMA = "fwe-mcu-advice/1"
_HEADER = re.compile(r"^(J|P|CN|TP|X)\d")
# What a flashing host reaches a pin through: a header, a USB-UART bridge, a button, an auto-reset transistor.
_REACH = re.compile(r"^(J|P|CN|TP|X|U|SW|Q)\d")


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


def _reaches(nl: Netlist, net: str, mcu: str) -> bool:
    """A header, bridge, button or transistor on the net, directly or through one series resistor."""
    for ref, pin in nl.refs_on(net):
        if ref == mcu:
            continue
        if _REACH.match(ref):
            return True
        if ref.startswith("R") and not ref.startswith("RN"):
            o = nl.other_net(ref, pin)
            if o and nl.volts(o) is None and any(_REACH.match(r) for r, _ in nl.refs_on(o) if r != mcu):
                return True
    return False


def _held(nl: Netlist, net: str | None) -> tuple[str | None, list[str]]:
    """How the board holds a pin at reset: "high" or "low" (by a rail or resistors to one), "both", or None."""
    if _unconnected(net):
        return None, []
    v = nl.volts(net)
    if v is not None:
        return ("high" if v > 0 else "low"), [short(net)]
    rs = _to_rails(nl, net, "R")
    ups, downs = [r for r, v in rs if v > 0], [r for r, v in rs if v == 0]
    if ups and downs:
        return "both", ups + downs
    return ("high", ups) if ups else ("low", downs) if downs else (None, [])


# gpio -> (strap name, the level that breaks it, the severity, why), from the ESP32 datasheet's strapping table.
ESP32_STRAPS = {
    0: ("GPIO0", "low", "must", "GPIO0 low at reset starts the ROM's download mode, never the firmware"),
    2: ("GPIO2", "high", "must", "the ROM enters download mode only with GPIO2 low or floating, "
                                 "so the ROM flash fails"),
    12: ("GPIO12 (MTDI)", "high", "must", "MTDI high at reset sets the flash supply to 1.8 V; a module's 3.3 V "
                                          "flash (WROOM-32, WROVER-E) then fails to boot"),
    15: ("GPIO15 (MTDO)", "low", "should", "MTDO low at reset silences the ROM's boot log on UART0, the rst line "
                                           "npie's boot step reads"),
}


def esp32_strap_advice(nl: Netlist, mcu: str, io: dict) -> list[dict]:
    out = []
    for gpio, (name, bad, sev, why) in ESP32_STRAPS.items():
        pin, net = f"GPIO{gpio}", io.get(gpio)
        level, by = _held(nl, net)
        if level == bad:
            out.append(_item("boot", sev, pin, net, f"{name} is held {bad} by {', '.join(by)}; take it off "
                             f"{short(net)} or hold it {'high' if bad == 'low' else 'low'}", why))
        elif level == "both":
            out.append(_item("boot", "should", pin, net, f"{name} is pulled both ways ({', '.join(by)})",
                             "a divider leaves the boot mode to resistor tolerances"))
    net = io.get(0)
    if _unconnected(net) or not _reaches(nl, net, mcu):
        out.append(_item("boot", "should", "GPIO0", net,
                         "give GPIO0 a BOOT button to GND or the UART header's auto-reset",
                         "the ROM flash needs GPIO0 low while EN rises; nothing on the board can pull it"))
    return out


def esp32_en_advice(nl: Netlist, pin: str, net: str | None) -> list[dict]:
    level, _ = _held(nl, net)
    if level not in ("high", "both"):
        return [_item("reset", "must", pin, net, "pull EN to 3V3 through 10k, with 1 uF to GND",
                      "EN is the chip's enable; floating or low, the ESP32 stays off or resets at random")]
    if nl.volts(net) is not None:
        return [_item("reset", "should", pin, net, f"put 10k between EN and {short(net)}, with 1 uF to GND",
                      "tied to the rail, EN has no RC delay and no host or button can reset the chip")]
    if not any(v == 0 for _, v in _to_rails(nl, net, "C")):
        return [_item("reset", "should", pin, net, "add 1 uF from EN to GND",
                      "Espressif's hardware design guidelines ask for the RC delay so EN rises after 3V3 settles")]
    return []


def esp32_uart_advice(nl: Netlist, mcu: str, io: dict) -> list[dict]:
    out = []
    for gpio, sig in ((1, "U0TXD"), (3, "U0RXD")):
        pin, net = f"GPIO{gpio}", io.get(gpio)
        role = None if _unconnected(net) else squeezelite.classify(net)[0]
        if _unconnected(net):
            out.append(_item("uart", "must", pin, net, f"bring {pin} ({sig}) to a UART header or USB-UART bridge",
                             "UART0 is the ROM bootloader's only port; without it the board can't be flashed"))
        elif role not in (None, "uart"):
            out.append(_item("uart", "must", pin, net, f"give {pin} to {sig} and move {short(net)} to another pin",
                             "UART0 is the ROM bootloader's port and the boot log's; firmware driving it "
                             "as anything else breaks both"))
        elif not _reaches(nl, net, mcu):
            out.append(_item("uart", "should", pin, net, f"bring {short(net)} to a UART header or USB-UART bridge",
                             "the ROM flash and npie's boot step both use UART0"))
    return out


def advise_esp32(nl: Netlist, mcu: str) -> tuple[str, list[dict]]:
    io, en = {}, None
    for num, net in nl.pins[mcu].items():
        func = nl.func[(mcu, num)]
        g = squeezelite.gpio_of(func)
        if g is not None:
            io[g] = net
        elif re.sub(r"_\d+$", "", func).upper() in ("EN", "CHIP_PU"):
            en = net
    advice = esp32_strap_advice(nl, mcu, io) + esp32_en_advice(nl, "EN", en) + esp32_uart_advice(nl, mcu, io)
    return "esp32", advice


def advise(ws: Path, mcu_ref: str | None) -> dict:
    nets = sorted((ws / "kicad").glob("*.net"))
    if len(nets) != 1:
        raise Error(f"expected one netlist in {ws / 'kicad'}, found {len(nets)}")
    netfile = nets[0]
    nl = Netlist(parse_netlist(netfile))
    mcu = pinmap.find_mcu(nl, mcu_ref)
    part = nl.comps[mcu]["value"]
    if part.upper().startswith("ESP32"):
        if squeezelite.later_series(part):
            raise Error(f"{part} is an {squeezelite.later_series(part)}; only the classic ESP32's straps are known")
        fam, advice = advise_esp32(nl, mcu)
        return _result(ws, netfile, mcu, part, fam, advice)
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
    return _result(ws, netfile, mcu, part, fam, advice)


def _result(ws: Path, netfile: Path, mcu: str, part: str, fam: str, advice: list[dict]) -> dict:
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
