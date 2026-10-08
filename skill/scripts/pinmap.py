#!/usr/bin/env python3
"""pinmap.py - derive a firmware pin map from an hwde board's netlist.

Reads <workspace>/kicad/<ws>.net (hwde's KiCad export), finds the MCU, and
classifies every MCU pin by the name of the net it sits on (ROLES below). For
each role it picks the peripheral function from the MCU's pin table
(reference/mcu/<family>.json, taken from the datasheet): gate-driver inputs
share one timer with CHn on the high side and CHnN on the low side, Hall and
encoder inputs share one timer, UART pins share one USART, a half-bridge's
PWM_HI/PWM_LO pair shares one HRTIM timer, analog inputs get an ADC channel.
It also derives the analog scaling from the parts on the nets: divider ratios
(through a series filter resistor and series resistor chains), a
current-sense amplifier's gain (from its part suffix), reference voltage
(from its REF pins' rails) and shunt value, an NTC's pull-up and beta. On an
HRTIM board it lists fault_routes: the comparator on each trip sense pin and,
once the MCU table's COMP -> FLTn sources are verified, the FLTn it reaches.

Writes <workspace>/firmware/pinmap.json and <workspace>/firmware/gen/board_pins.h.
With --check it writes nothing and exits 1 when either file differs from what
the netlist gives now, so a re-spun board fails the firmware build until the
map is regenerated.

JSON to stdout (or --out): {"ok", "board", "mcu", "pins", "analog", "rails",
"fault_routes" (HRTIM boards only), "findings", "files"}. Exit 0 ok, 1 findings or drift (--check), 2 error.
A finding is anything the map could not derive (an unclassified pin, an
analog input with no ADC channel, a timer group with no common timer, a
COMP -> FLTn route the MCU table has not verified); it is reported, never
guessed.
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
from fwelib.netlist import NetlistError, parse_netlist  # noqa: E402

MCU_DIR = fwenv.SKILL / "reference" / "mcu"
PHASE_CH = {"A": 1, "B": 2, "C": 3}

# (net-name regex, role, group). A group's pins must share one peripheral.
ROLES = [
    (r"INH([A-C])", "gate_hi", "pwm"),
    (r"INL([A-C])", "gate_lo", "pwm"),
    (r"ISENSE_([A-C])", "i_sense", None),
    (r"VSENSE_([A-C])", "v_phase", None),
    (r"VBUS_SENSE", "v_bus", None),
    (r"PWM_(HI)", "hrtim_hi", "hrtim"),
    (r"PWM_(LO)", "hrtim_lo", "hrtim"),
    (r"ISNS", "i_sense", None),
    (r"VOUT_SNS", "v_out", None),
    (r"VIN_SNS", "v_in", None),
    (r"NTC_SNS", "ntc", None),
    (r"FAN_PWM", "fan_pwm", "fan"),
    (r"HALL_([A-C])", "hall", "hall"),
    (r"ENC_([AB])", "encoder", "encoder"),
    (r"ENC_(Z)", "encoder_index", None),
    (r"UART_(TX)", "uart_tx", "uart"),
    (r"UART_(RX)", "uart_rx", "uart"),
    (r"LED_(\w+)", "led", None),
    (r"(\w+)_SW", "button", None),
    (r"SW_(\w+)", "button", None),
    (r"SWDIO|SWCLK", "swd", None),
    (r"NRST", "reset", None),
    (r"BOOT0", "boot", None),
]
ANALOG_ROLES = {"i_sense", "v_phase", "v_bus", "v_out", "v_in", "ntc"}
DIVIDER_ROLES = {"v_bus", "v_phase", "v_out", "v_in"}
# Comparator trips a converter routes to an HRTIM fault input, by sense role.
TRIP = {"i_sense": "ocp", "v_out": "ovp"}
# Current-sense amplifiers: part prefix -> {suffix: V/V}. Datasheet gains.
CSA_GAIN = {
    "INA240": {"A1": 20, "A2": 50, "A3": 100, "A4": 200},
    "INA181": {"A1": 20, "A2": 50, "A3": 100, "A4": 200},
    "INA180": {"A1": 20, "A2": 50, "A3": 100, "A4": 200},
}
_GPIO = re.compile(r"^(P[A-K]\d{1,2})")
_RAIL = re.compile(r"^\+?(\d+)V(\d*)$")
_VAL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mR|m|k|K|M|R|ohm|Ohm|Ω)?(\d*)")
_MULT = {"m": 1e-3, "mR": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6}


class Error(Exception):
    pass


def short(net: str) -> str:
    """'/mcu/LED_FAULT' -> 'LED_FAULT'; '+3V3' stays."""
    return net.rsplit("/", 1)[-1]


def ohms(value: str | None) -> float | None:
    """'150k' 150e3, '3mR 2512' 0.003, '100 ohm' 100, '4k7' 4700, '3.3R DNP' 3.3."""
    m = _VAL.match(value or "")
    if not m:
        return None
    num, unit, frac = m.groups()
    v = float(num + ("." + frac if frac else ""))
    return v * _MULT.get(unit or "", 1.0)


def rail_volts(net: str) -> float | None:
    s = short(net)
    if s.upper() in ("GND", "VSS", "AGND", "GNDA"):
        return 0.0
    m = _RAIL.match(s)
    return float(f"{m.group(1)}.{m.group(2) or 0}") if m else None


class Netlist:
    def __init__(self, parsed: dict):
        self.comps = parsed["components"]
        self.nets = parsed["nets"]
        self.pins: dict[str, dict[str, str]] = {}      # ref -> pin -> net
        self.func: dict[tuple[str, str], str] = {}     # (ref, pin) -> pinfunction
        for net, nodes in self.nets.items():
            for nd in nodes:
                self.pins.setdefault(nd["ref"], {})[nd["pin"]] = net
                self.func[(nd["ref"], nd["pin"])] = nd.get("pinfunction") or ""

    def refs_on(self, net: str) -> list[tuple[str, str]]:
        return [(nd["ref"], nd["pin"]) for nd in self.nets.get(net, [])]

    def other_net(self, ref: str, pin: str) -> str | None:
        """The net on the other pin of a 2-pin part."""
        pins = self.pins.get(ref, {})
        rest = [n for p, n in pins.items() if p != pin]
        return rest[0] if len(pins) == 2 and rest else None

    def volts(self, net: str, seen=None) -> float | None:
        """A rail's voltage from its name, or through a ferrite/0R/net tie."""
        v = rail_volts(net)
        if v is not None:
            return v
        seen = (seen or set()) | {net}
        for ref, pin in self.refs_on(net):
            if ref[:2] in ("FB", "NT") or (ref[0] == "R" and ohms(self.comps[ref]["value"]) == 0):
                o = self.other_net(ref, pin)
                if o and o not in seen:
                    v = self.volts(o, seen)
                    if v is not None:
                        return v
        return None

    def tied(self, net: str) -> set[str]:
        """net plus every net joined to it through net ties."""
        out, todo = {net}, [net]
        while todo:
            n = todo.pop()
            for ref, pin in self.refs_on(n):
                if ref.startswith("NT"):
                    o = self.other_net(ref, pin)
                    if o and o not in out:
                        out.add(o)
                        todo.append(o)
        return out


def load_mcu_table(part: str) -> tuple[str, dict]:
    m = re.match(r"STM32([A-Z]\d)(\d\d)", part.upper())
    fam = f"stm32{m.group(1).lower()}{m.group(2)}" if m else None
    path = MCU_DIR / f"{fam}.json" if fam else None
    if not path or not path.is_file():
        raise Error(f"no pin table for {part} (want {path}); extract one from the datasheet")
    return fam, json.loads(path.read_text(encoding="utf-8"))


def find_mcu(nl: Netlist, ref: str | None) -> str:
    if ref:
        if ref not in nl.comps:
            raise Error(f"--mcu {ref} is not in the netlist")
        return ref
    cands = [r for r, c in nl.comps.items() if re.match(r"STM32", c.get("value") or "", re.I)]
    if len(cands) != 1:
        raise Error(f"expected one STM32 in the netlist, found {cands or 'none'}; pass --mcu")
    return cands[0]


def classify(net: str) -> tuple[str | None, str | None, str | None]:
    s = short(net)
    for rx, role, group in ROLES:
        m = re.fullmatch(rx, s)
        if m:
            return role, group, (m.group(1) if m.groups() else None)
    return None, None, None


def pick_group(members: list[dict], table: dict, rx: str, want) -> tuple[str | None, dict]:
    """Common peripheral for a group. rx captures (peripheral, channel) from an
    AF name; want(member, channel_str) says whether that AF fits the member."""
    per_pin = []
    for m in members:
        opts = {}
        for af_name, af in table["pins"].get(m["pin"], {}).get("af", {}).items():
            mm = re.fullmatch(rx, af_name)
            if mm and want(m, mm.group(2)):
                opts.setdefault(mm.group(1), (af_name, af))
        per_pin.append(opts)
    common = set(per_pin[0]).intersection(*per_pin[1:]) if per_pin else set()
    if not common:
        return None, {}
    best = min(common, key=lambda p: (len(p), p))
    return best, {m["pin"]: opts[best] for m, opts in zip(members, per_pin)}


def assign_functions(pins: list[dict], table: dict, findings: list) -> None:
    groups: dict[str, list[dict]] = {}
    for p in pins:
        if p.get("group"):
            groups.setdefault(p["group"], []).append(p)
    rules = {
        "pwm": (r"(TIM\d+)_CH(\d+N?)", lambda m, ch: ch == f"{PHASE_CH[m['tag']]}"
                + ("N" if m["role"] == "gate_lo" else "")),
        "hall": (r"(TIM\d+)_CH(\d+)", lambda m, ch: ch == str(PHASE_CH[m["tag"]])),
        "encoder": (r"(TIM\d+)_CH(\d+)", lambda m, ch: ch == {"A": "1", "B": "2"}[m["tag"]]),
        "uart": (r"(U?S?ART\d+)_(TX|RX)", lambda m, ch: ch == m["tag"]),
        # A half-bridge pair: both outputs of one HRTIM timer (CHx1, CHx2).
        "hrtim": (r"HRTIM1_CH([A-F])([12])", lambda m, ch: True),
        "fan": (r"(TIM\d+)_CH(\d+)", lambda m, ch: True),
    }
    for g, members in sorted(groups.items()):
        rx, want = rules[g]
        per, chosen = pick_group(members, table, rx, want)
        if not per:
            findings.append({"kind": "no_common_peripheral", "group": g,
                             "pins": [m["pin"] for m in members],
                             "detail": f"no single peripheral serves every {g} pin in its role"})
            continue
        if g == "hrtim" and len({chosen[m["pin"]][0] for m in members}) != len(members):
            findings.append({"kind": "hrtim_pair_clash", "pins": [m["pin"] for m in members],
                             "detail": "the half-bridge inputs need different outputs of one timer"})
            continue
        for m in members:
            name, af = chosen[m["pin"]]
            m["function"] = {"name": name, "af": af,
                             "peripheral": f"HRTIM1_TIM{per}" if g == "hrtim" else per}
            if g == "hrtim":
                m["function"]["output"] = int(name[-1])
    for p in pins:
        if p["role"] in ANALOG_ROLES:
            adc = sorted(a for a in table["pins"].get(p["pin"], {}).get("analog", [])
                         if re.fullmatch(r"ADC\d+_IN\d+", a))
            comp = sorted(a for a in table["pins"].get(p["pin"], {}).get("analog", [])
                          if re.fullmatch(r"COMP\d+_INP", a))
            if not adc:
                findings.append({"kind": "no_adc_channel", "pin": p["pin"], "net": p["net"]})
                continue
            m = re.fullmatch(r"ADC(\d+)_IN(\d+)", adc[0])
            p["function"] = {"name": adc[0], "adc": int(m.group(1)[0]), "channel": int(m.group(2))}
            if comp and p["role"] != "ntc":
                p["comparator"] = comp[0]


def _nodes(nl: Netlist, net: str) -> list[tuple[str, str | None]]:
    """The pin's net, then the far side of each resistor on it: a sense line
    may reach its divider or pull-up through a series filter resistor.
    Pairs (node, series resistor or None)."""
    out = [(net, None)]
    for ref, rp in nl.refs_on(net):
        o = nl.other_net(ref, rp) if ref.startswith("R") else None
        if o and rail_volts(o) is None:
            out.append((o, ref))
    return out


def _chain(nl: Netlist, ref: str, far: str) -> tuple[list[str], float | None, str]:
    """Follow resistors in series from ref's far net (through nets that hold
    only two resistors) to where the chain ends. (parts, ohms, end net)."""
    parts, total = [ref], ohms(nl.comps[ref]["value"])
    while total is not None and rail_volts(far) is None:
        nxt = [(r, p) for r, p in nl.refs_on(far) if r not in parts]
        if len(nl.refs_on(far)) != 2 or len(nxt) != 1 or not nxt[0][0].startswith("R"):
            break
        r, p = nxt[0]
        o = nl.other_net(r, p)
        v = ohms(nl.comps[r]["value"])
        if o is None or v is None:
            break
        parts.append(r)
        total += v
        far = o
    return parts, total, far


def _divider(nl: Netlist, net: str) -> dict | None:
    for node, series in _nodes(nl, net):
        top = bot = None
        for ref, rp in nl.refs_on(node):
            o = nl.other_net(ref, rp) if ref.startswith("R") and ref != series else None
            if o is None:
                continue
            if rail_volts(o) == 0.0:
                bot = (ref, ohms(nl.comps[ref]["value"]))
            else:
                parts, r, end = _chain(nl, ref, o)
                top = (parts, r, short(end))
        if top and bot and top[1] and bot[1]:
            return {"kind": "divider", "source": top[2], "r_top": top[1], "r_bot": bot[1],
                    "ratio": round((top[1] + bot[1]) / bot[1], 6), "parts": [*top[0], bot[0]]}
    return None


def _ntc(nl: Netlist, net: str) -> dict | None:
    """A thermistor to ground with a pull-up to a rail."""
    for node, series in _nodes(nl, net):
        up = ntc = None
        for ref, rp in nl.refs_on(node):
            o = nl.other_net(ref, rp)
            if o is None or ref == series:
                continue
            value = nl.comps[ref]["value"] or ""
            if ref.startswith("RT") and rail_volts(o) == 0.0:
                b = re.search(r"B\s*(\d{4})", value)
                ntc = (ref, value, ohms(value), int(b.group(1)) if b else None)
            elif ref.startswith("R") and nl.volts(o):
                up = (ref, ohms(value), short(o), nl.volts(o))
        if up and ntc and up[1] and ntc[2] and ntc[3]:
            return {"kind": "ntc", "ntc": ntc[0], "ntc_part": ntc[1], "r25_ohm": ntc[2],
                    "beta": ntc[3], "pullup": up[0], "pullup_ohm": up[1], "rail": up[2],
                    "rail_v": up[3]}
    return None


def analog_scaling(nl: Netlist, pin: dict, findings: list) -> dict | None:
    net = pin["net_full"]
    if pin["role"] in DIVIDER_ROLES:
        d = _divider(nl, net)
        if not d:
            findings.append({"kind": "no_divider", "net": pin["net"]})
        return d
    if pin["role"] == "ntc":
        t = _ntc(nl, net)
        if not t:
            findings.append({"kind": "no_ntc", "net": pin["net"]})
        return t
    # i_sense: [MCU] - series R - amp OUT; amp IN+/IN- across a shunt
    for ref, rp in nl.refs_on(net):
        if not ref.startswith("R"):
            continue
        o = nl.other_net(ref, rp)
        for aref, apin in nl.refs_on(o or ""):
            if nl.func.get((aref, apin), "").upper().startswith("OUT"):
                return _csa(nl, pin, aref, ref, findings)
    findings.append({"kind": "no_current_amp", "net": pin["net"]})
    return None


def _csa(nl: Netlist, pin: dict, amp: str, series_r: str, findings: list) -> dict | None:
    value = nl.comps[amp]["value"] or ""
    gain = None
    for prefix, table in CSA_GAIN.items():
        if value.upper().startswith(prefix):
            gain = table.get(value.upper()[len(prefix):len(prefix) + 2])
    by_func = {nl.func[(amp, p)].split("_")[0].upper(): n for p, n in nl.pins[amp].items()}
    refs = [nl.volts(n) for f, n in by_func.items() if re.fullmatch(r"REF\d?", f)]
    ref_v = sum(refs) / len(refs) if refs and None not in refs else None
    plus, minus = nl.tied(by_func.get("IN+", "")), nl.tied(by_func.get("IN-", ""))
    shunt = None
    for r, pins in nl.pins.items():
        if r.startswith("R") and len(pins) == 2:
            a, b = pins.values()
            if (a in plus and b in minus) or (b in plus and a in minus):
                shunt = (r, ohms(nl.comps[r]["value"]))
    if gain is None or ref_v is None or not shunt or not shunt[1]:
        findings.append({"kind": "current_scaling_incomplete", "net": pin["net"], "amp": amp,
                         "gain": gain, "ref_v": ref_v, "shunt": shunt})
        return None
    return {"kind": "current", "amp": amp, "amp_part": value, "gain_v_per_v": gain,
            "ref_v": round(ref_v, 6), "shunt": shunt[0], "shunt_ohm": shunt[1],
            "volts_per_amp": round(gain * shunt[1], 9), "series_r": series_r}


def fault_routes(pins: list[dict], table: dict, findings: list) -> list[dict]:
    """COMP -> HRTIM fault routes, for a board whose switches an HRTIM drives:
    the comparator on each trip sense pin, and the FLTn input that comparator
    reaches inside the chip, read from the MCU table's fault_internal_sources.
    The FLTn number is reported only once that table is verified against the
    reference manual; until then each route is a finding, never a guess."""
    if not any(p["role"].startswith("hrtim_") for p in pins):
        return []
    src = table.get("hrtim", {}).get("fault_internal_sources", {})
    by_comp = {c: f for f, c in src.get("map", {}).items()}
    routes = []
    for p in pins:
        if p["role"] not in TRIP:
            continue
        if not p.get("comparator"):
            findings.append({"kind": "no_trip_comparator", "pin": p["pin"], "net": p["net"],
                             "detail": f"{TRIP[p['role']]} needs a COMPx_INP on this pin"})
            continue
        comp = p["comparator"].split("_")[0]
        flt = by_comp.get(comp) if src.get("status") == "verified" else None
        routes.append({"trip": TRIP[p["role"]], "net": p["net"], "pin": p["pin"],
                       "comp": comp, "fault": flt,
                       "verified_against": src.get("verified_against") if flt else None})
        if not flt:
            findings.append({"kind": "fault_route_unverified", "net": p["net"], "comp": comp,
                             "detail": "the COMP -> HRTIM FLTn source is not verified in the MCU "
                                       "table (hrtim.fault_internal_sources)"})
    return routes


def build(ws: Path, mcu_ref: str | None) -> dict:
    nets = sorted((ws / "kicad").glob("*.net"))
    if len(nets) != 1:
        raise Error(f"expected one netlist in {ws / 'kicad'}, found {len(nets)}")
    netfile = nets[0]
    nl = Netlist(parse_netlist(netfile))
    mcu = find_mcu(nl, mcu_ref)
    part = nl.comps[mcu]["value"]
    fam, table = load_mcu_table(part)
    findings: list[dict] = []
    pins, power = [], {}
    for num, net in sorted(nl.pins[mcu].items(), key=lambda kv: int(kv[0])):
        func = nl.func[(mcu, num)]
        g = _GPIO.match(func)
        if not g:
            power.setdefault(short(net), []).append(func.rsplit("_", 1)[0])
            continue
        io = g.group(1)
        if short(net).startswith("unconnected-"):
            pins.append({"pin": io, "number": int(num), "net": None, "role": "unused"})
            continue
        role, group, tag = classify(net)
        p = {"pin": io, "number": int(num), "net": short(net), "net_full": net,
             "role": role or "unclassified"}
        if tag:
            p["tag"] = tag
        if group:
            p["group"] = group
        if role is None:
            findings.append({"kind": "unclassified", "pin": io, "net": short(net)})
        if io not in table["pins"]:
            findings.append({"kind": "pin_not_in_table", "pin": io, "table": fam})
        pins.append(p)
    assign_functions(pins, table, findings)
    faults = fault_routes(pins, table, findings)
    analog = {}
    for p in pins:
        if p["role"] in ANALOG_ROLES:
            s = analog_scaling(nl, p, findings)
            if s:
                analog[p["net"]] = s
    rails = {}
    for net in sorted(power):
        v = nl.volts(next(n for n in nl.nets if short(n) == net))
        rails[net] = v
    for p in pins:
        p.pop("net_full", None)
        p.pop("group", None)
    ws_name = ws.name
    return {"board": ws_name.split("_", 1)[0], "workspace": ws_name,
            "netlist": f"kicad/{netfile.name}",
            "netlist_sha256": hashlib.sha256(netfile.read_bytes()).hexdigest(),
            "mcu": {"ref": mcu, "part": part, "table": fam, "source": table.get("source")},
            "pins": pins, "power_pins": power, "rails": rails, "analog": analog,
            **({"fault_routes": faults} if faults else {}), "findings": findings}


def _c(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def _f(x: float) -> str:
    """A C float literal: 16 -> 16.0f, 0.003 -> 0.003f (plain `16f` is not C)."""
    s = f"{x:.6g}"
    return s + ("f" if any(c in s for c in ".e") else ".0f")


def header(m: dict) -> str:
    out = ["/* board_pins.h - GENERATED by /fwe pinmap.py from "
           f"{m['workspace']}/{m['netlist']}.", " * Do not edit: regenerate with "
           "pinmap.py --workspace <board>; the build runs pinmap.py --check.",
           f" * netlist sha256 {m['netlist_sha256']} */",
           "#ifndef BOARD_PINS_H", "#define BOARD_PINS_H", "",
           f"#define BOARD_ID \"{m['board']}\"", f"#define BOARD_MCU \"{m['mcu']['part']}\"", ""]
    for p in m["pins"]:
        if p["role"] == "unused":
            continue
        n = "PIN_" + _c(p["net"])
        out.append(f"/* {p['pin']} (pin {p['number']}) {p['role']} */")
        out.append(f"#define {n}_PORT GPIO{p['pin'][1]}")
        out.append(f"#define {n}_PIN {int(p['pin'][2:])}u")
        f = p.get("function", {})
        if "af" in f:
            out.append(f"#define {n}_AF {f['af']}u /* {f['name']} */")
        if "output" in f:
            out.append(f"#define {n}_HRTIM_TIMER {ord(f['peripheral'][-1]) - ord('A')}u "
                       f"/* {f['peripheral']} */")
            out.append(f"#define {n}_HRTIM_OUT {f['output']}u")
        if "adc" in f:
            out.append(f"#define {n}_ADC {f['adc']}u")
            out.append(f"#define {n}_ADC_CH {f['channel']}u /* {f['name']} */")
        if p.get("comparator"):
            out.append(f"#define {n}_COMP {int(re.search(r'\d+', p['comparator']).group())}u "
                       f"/* {p['comparator']} */")
        out.append("")
    unused = [p["pin"] for p in m["pins"] if p["role"] == "unused"]
    out.append(f"/* unused: {' '.join(unused) or 'none'} */")
    for net, v in m["rails"].items():
        if v:
            out.append(f"#define RAIL_{_c(net)}_V {_f(v)}")
    out.append("")
    for net, a in m["analog"].items():
        n = _c(net)
        if a["kind"] == "divider":
            out.append(f"#define {n}_RATIO {_f(a['ratio'])} /* {a['source']}: "
                       f"{a['r_top']:g}/{a['r_bot']:g} ohm */")
        elif a["kind"] == "ntc":
            out.append(f"#define {n}_PULLUP_OHM {_f(a['pullup_ohm'])} /* {a['pullup']} to {a['rail']} */")
            out.append(f"#define {n}_R25_OHM {_f(a['r25_ohm'])} /* {a['ntc']} {a['ntc_part']} */")
            out.append(f"#define {n}_BETA {_f(a['beta'])}")
        else:
            out.append(f"#define {n}_GAIN {_f(a['gain_v_per_v'])} /* {a['amp']} {a['amp_part']} */")
            out.append(f"#define {n}_REF_V {_f(a['ref_v'])}")
            out.append(f"#define {n}_SHUNT_OHM {_f(a['shunt_ohm'])} /* {a['shunt']} */")
    for r in m.get("fault_routes", []):
        n = _c(r["net"])
        out.append("")
        out.append(f"/* {r['trip']}: {r['net']} -> {r['comp']} -> HRTIM "
                   f"{r['fault'] or 'FLTn UNVERIFIED (pinmap finding)'} */")
        out.append(f"#define TRIP_{r['trip'].upper()}_COMP {r['comp'][4:]}u")
        if r["fault"]:
            out.append(f"#define TRIP_{r['trip'].upper()}_FLT {r['fault'][3:]}u "
                       f"/* {r['verified_against']} */")
    out += ["", "#endif /* BOARD_PINS_H */", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--mcu", help="MCU refdes when the netlist has more than one STM32")
    ap.add_argument("--fw-dir", default="firmware", help="firmware dir, relative to the workspace")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on drift")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    res: dict
    try:
        if Path(a.fw_dir).is_absolute() or ".." in Path(a.fw_dir).parts:
            raise Error(f"--fw-dir {a.fw_dir} must be a path inside the workspace")
        m = build(ws, a.mcu)
    except (Error, NetlistError, OSError) as exc:
        res, rc = {"ok": False, "error": str(exc)}, 2
    else:
        fw = ws / a.fw_dir
        want = {fw / "pinmap.json": json.dumps(m, indent=2) + "\n",
                fw / "gen" / "board_pins.h": header(m)}
        drift = []
        for path, text in want.items():
            have = path.read_text(encoding="utf-8") if path.is_file() else None
            if have != text:
                drift.append(str(path.relative_to(ws)))
                if not a.check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
        res = {"ok": not m["findings"] and not (a.check and drift), **m,
               "files": [str(p.relative_to(ws)) for p in want],
               ("drift" if a.check else "written"): drift}
        rc = 0 if res["ok"] else 1
    text = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
