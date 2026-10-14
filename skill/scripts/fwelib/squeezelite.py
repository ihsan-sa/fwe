"""squeezelite.py - the ESP32 branch of pinmap.py: a squeezelite-esp32 board's
NVS config from its netlist.

squeezelite-esp32 reads its whole board description from NVS strings in the
`config` namespace (dac_config, set_GPIO, i2c_config, eth_config, ...), so on
an ESP32 board the pin map's product is that config, written as the CSV
ESP-IDF's nvs_partition_gen.py turns into the NVS partition image the flash
step loads. What our own components need and upstream has no key for (the
line-in ADC, the amp's warning pin, the buttons) goes in a second namespace,
`fwe`, so upstream never sees a key it does not know.

Two sources decide a pin. A recognised part (reference/esp32/codecs.json,
by part-number prefix) names its control pins, and the GPIO is whichever
module pin shares that pin's net, so the net's name does not matter. Every
other pin is classified by its net name (ROLES). Anything the map cannot
derive (an unverified codec sequence, an I2C address the straps do not fix,
an output on an input-only pin, an RMII pin taken by something else) is a
finding, never a guess.
"""
from __future__ import annotations

import csv
import io
import json
import re

# A later ESP32 series (ESP32-C3, -S3, -S2, -C6, -H2, -P4, ...) has other pins and
# another core; this target's tables are the classic ESP32's (WROVER, WROOM-32,
# PICO-D4, SOLO-1, D0WD).
_LATER = re.compile(r"ESP32-?([CSHP]\d+)", re.I)


def later_series(part: str) -> str | None:
    """"ESP32-S3" for an ESP32-S3 part and so on, None for a classic ESP32."""
    m = _LATER.match(part.strip())
    return f"ESP32-{m.group(1).upper()}" if m else None


# ESP32 module pin functions that are GPIOs, besides IO<n>/GPIO<n>.
_ALIAS = {"SENSOR_VP": 36, "SENSOR_VN": 39, "TXD0": 1, "RXD0": 3, "U0TXD": 1, "U0RXD": 3}
_IO = re.compile(r"^(?:GPIO|IO)(\d{1,2})$")
INPUT_ONLY = {34, 35, 36, 37, 38, 39}
RESERVED = {6, 7, 8, 9, 10, 11, 16, 17}     # SPI flash and, on a WROVER, PSRAM
STRAPPING = {0, 2, 5, 12, 15}
# ESP32 EMAC RMII pins are fixed in silicon (TRM, EMAC chapter).
RMII = {19: "TXD0", 21: "TX_EN", 22: "TXD1", 25: "RXD0", 26: "RXD1", 27: "CRS_DV"}

# (net-name regex, role, direction). Direction "out" may not sit on an input-only pin.
ROLES = [
    (r"I2S_(?:BCK|BCLK|SCK)", "i2s_bck", "out"),
    (r"I2S_(?:WS|LRCK|LRCLK|FS)", "i2s_ws", "out"),
    (r"I2S_(?:DO|DOUT|SDOUT|DATA_OUT|DATA)", "i2s_do", "out"),
    (r"I2S_(?:DI|DIN|SDIN|DATA_IN)", "i2s_di", "in"),
    (r"I2S_MCLK|MCLK", "i2s_mck", "out"),
    (r"I2C_SDA|SDA", "i2c_sda", "out"),
    (r"I2C_SCL|SCL", "i2c_scl", "out"),
    (r"ETH_MDC|MDC", "eth_mdc", "out"),
    (r"ETH_MDIO|MDIO", "eth_mdio", "out"),
    (r"(?:ETH|PHY)_RST\w*|(?:ETH|PHY)_RESET\w*", "eth_rst", "out"),
    (r"(?:ETH|RMII)_(?:CLK|REF_CLK|CLK_IN)|RMII_CLK", "eth_clk", "in"),
    (r"RMII_(TXD0|TX_EN|TXD1|RXD0|RXD1|CRS_DV)", "rmii", None),
    (r"SPI_(?:MOSI|SDO|DATA)", "spi_mosi", "out"),
    (r"SPI_(?:SCK|CLK)", "spi_clk", "out"),
    (r"(?:DISP|LCD|OLED)_CS", "disp_cs", "out"),
    (r"(?:DISP|LCD|OLED)_DC", "disp_dc", "out"),
    (r"(?:DISP|LCD|OLED)_(?:RST|RESET)", "disp_rst", "out"),
    (r"(?:DISP|LCD|OLED)_(?:BL|BACKLIGHT)", "disp_bl", "out"),
    (r"IR_(?:RX|IN)|IR", "ir", "in"),
    (r"(?:JACK|HP)_DET\w*", "jack", "in"),
    (r"(?:ENC|ROT)_(A)", "enc_a", "in"),
    (r"(?:ENC|ROT)_(B)", "enc_b", "in"),
    (r"(?:ENC|ROT)_(?:SW|BTN|PUSH)", "enc_sw", "in"),
    (r"(?:BTN|KEY|SW)_(\w+)", "button", "in"),
    (r"LED_(GREEN|GRN|G)", "led_green", "out"),
    (r"LED_(RED|R)", "led_red", "out"),
    (r"LED_(\w+)", "led", "out"),
    (r"(?:AMP_)?(?:EN|ENABLE|PDN|RESET|nRESET)", "amp_en", "out"),
    (r"(?:AMP_)?(?:FAULT|nFAULT|FLT)", "amp_fault", "in"),
    (r"(?:AMP_)?(?:WARN|OTW|CLIP_OTW)", "amp_warn", "in"),
    (r"(?:DAC_)?(?:MUTE|XSMT|SMUTE)", "dac_mute", "out"),
    (r"(?:UART|U0)_?(TXD?|RXD?)", "uart", None),
    (r"BOOT|IO0_BOOT", "boot", "in"),
]
# A part's control pin -> the role it gives its GPIO and the level that means "on".
PART_PIN_ROLE = {"enable": ("amp_en", 1), "fault": ("amp_fault", 0),
                 "warn": ("amp_warn", 0), "mute": ("dac_mute", 0)}
DISPLAY_SIZE = {"SSD1306": (128, 64), "SH1106": (128, 64), "SSD1322": (256, 64), "ST7789": (240, 240)}


def gpio_of(func: str) -> int | None:
    """'IO25' 25, 'GPIO4' 4, 'IO25_10' (hwde's number suffix) 25, 'SENSOR_VP' 36, 'GND' None."""
    f = re.sub(r"_\d+$", "", func or "").upper()
    m = _IO.match(f)
    if m:
        return int(m.group(1))
    return _ALIAS.get(f)


def _pin_name(func: str) -> str:
    """'~{FAULT}' 'FAULT', '/RESET' 'RESET', 'PDN_3' 'PDN'."""
    return re.sub(r"_\d+$", "", re.sub(r"[~{}/]", "", func or "")).upper()


def classify(net: str) -> tuple[str | None, str | None, str | None]:
    s = net.rsplit("/", 1)[-1]
    for rx, role, d in ROLES:
        m = re.fullmatch(rx, s, re.I)
        if m:
            return role, d, (m.group(1).upper() if m.groups() else None)
    return None, None, None


def find_parts(nl, codecs: dict) -> list[dict]:
    """Every component whose value starts with a codecs.json part number."""
    out = []
    for ref, c in sorted(nl.comps.items()):
        val = (c.get("value") or "").upper()
        for pn, spec in codecs["parts"].items():
            if val.startswith(pn):
                out.append({"ref": ref, "part": c.get("value"), "key": pn, **spec})
                break
    return out


def _part_pin_net(nl, ref: str, name: str) -> str | None:
    for pin, net in nl.pins.get(ref, {}).items():
        if _pin_name(nl.func.get((ref, pin), "")) == name:
            return net
    return None


def _i2c_addr(nl, part: dict, findings: list) -> int | None:
    addrs = part.get("i2c_addr") or []
    if len(addrs) == 1:
        return addrs[0]
    straps = [n for p, n in nl.pins.get(part["ref"], {}).items()
              if re.match(r"ADR|ADDR|AD0|CAD0", _pin_name(nl.func.get((part["ref"], p), "")))]
    if len(straps) == 1 and len(addrs) >= 2:
        v = nl.volts(straps[0])
        if v == 0:
            return addrs[0]
        if v:
            return addrs[1]
    findings.append({"kind": "i2c_addr_unknown", "ref": part["ref"], "part": part["part"],
                     "detail": f"its address straps do not fix one of {addrs}"})
    return None


def build(nl, mcu: str, codecs: dict) -> dict:
    """pins, power_pins, squeezelite (namespace -> key -> value) and findings."""
    findings: list[dict] = []
    pins, power, by_net = [], {}, {}
    for num, net in sorted(nl.pins[mcu].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        func = nl.func[(mcu, num)]
        g = gpio_of(func)
        short = net.rsplit("/", 1)[-1]
        if g is None:
            power.setdefault(short, []).append(_pin_name(func))
            continue
        p = {"pin": f"GPIO{g}", "gpio": g, "number": int(num) if num.isdigit() else num}
        if short.startswith("unconnected-"):
            pins.append({**p, "net": None, "role": "unused"})
            continue
        p.update(net=short, role="unclassified")
        pins.append(p)
        by_net[net] = p
    parts = find_parts(nl, codecs)
    # A recognised part's control pins decide their GPIO's role, whatever the net is called.
    for part in parts:
        for what, name in part.get("pins", {}).items():
            if what not in PART_PIN_ROLE:
                continue
            net = _part_pin_net(nl, part["ref"], name)
            p = by_net.get(net) if net else None
            if p:
                p["role"], p["active"] = PART_PIN_ROLE[what]
                p["part"] = part["ref"]
    for p in pins:
        if p["role"] != "unclassified":
            continue
        role, _d, tag = classify(p["net"])
        if role is None:
            findings.append({"kind": "unclassified", "pin": p["pin"], "net": p["net"]})
            continue
        p["role"] = role
        if tag:
            p["tag"] = tag
    for p in pins:
        if p["role"] == "unused":
            continue
        g = p["gpio"]
        out = next((d for _rx, r, d in ROLES if r == p["role"]), None) == "out"
        if out and g in INPUT_ONLY:
            findings.append({"kind": "input_only_pin", "pin": p["pin"], "net": p["net"],
                             "detail": f"{p['role']} drives this pin; GPIO34-39 are inputs only"})
        if g in RESERVED:
            findings.append({"kind": "reserved_pin", "pin": p["pin"], "net": p["net"],
                             "detail": "GPIO6-11 are the module's flash and GPIO16/17 its PSRAM"})
    cfg, fwe = _config(nl, pins, parts, findings)
    notes = [f"{p['pin']} is a strapping pin ({p['net']}): keep its boot level"
             for p in pins if p["role"] != "unused" and p["gpio"] in STRAPPING]
    return {"pins": pins, "power_pins": power,
            "parts": [{"ref": x["ref"], "part": x["part"], "kind": x["kind"]} for x in parts],
            "squeezelite": {"config": cfg, "fwe": fwe}, "notes": notes, "findings": findings}


def _one(pins: list[dict], role: str, findings: list) -> dict | None:
    hits = [p for p in pins if p["role"] == role]
    if len(hits) > 1:
        findings.append({"kind": "duplicate_role", "role": role, "pins": [p["pin"] for p in hits]})
    return hits[0] if hits else None


def _config(nl, pins: list[dict], parts: list[dict], findings: list) -> tuple[dict, dict]:
    g = {r: _one(pins, r, findings) for r in
         ("i2s_bck", "i2s_ws", "i2s_do", "i2s_di", "i2s_mck", "i2c_sda", "i2c_scl", "eth_mdc",
          "eth_mdio", "eth_rst", "spi_mosi", "spi_clk", "disp_cs", "disp_dc", "disp_rst",
          "disp_bl", "enc_a", "enc_b", "enc_sw", "dac_mute", "ir", "jack")}
    cfg: dict[str, str] = {}
    fwe: dict[str, str] = {}
    i2c = g["i2c_sda"] and g["i2c_scl"]
    if i2c:
        cfg["i2c_config"] = f"scl={g['i2c_scl']['gpio']},sda={g['i2c_sda']['gpio']},speed=400000,port=0"

    sinks = [x for x in parts if x["kind"] in ("dac", "amp") and "i2s" in x.get("bus", "")]
    if len(sinks) > 1:
        findings.append({"kind": "several_i2s_sinks", "parts": [x["ref"] for x in sinks],
                         "detail": "squeezelite drives one dac_config; the first is used"})
    dac = sinks[0] if sinks else None
    if g["i2s_bck"] and g["i2s_ws"] and g["i2s_do"]:
        f = [f"model={dac['model'] if dac else 'I2S'}", f"bck={g['i2s_bck']['gpio']}",
             f"ws={g['i2s_ws']['gpio']}", f"do={g['i2s_do']['gpio']}"]
        if g["i2s_mck"]:
            f.append(f"mck={g['i2s_mck']['gpio']}")
            if g["i2s_mck"]["gpio"] not in (0, 1, 3):
                findings.append({"kind": "mclk_pin", "pin": g["i2s_mck"]["pin"],
                                 "detail": "the ESP32 puts I2S MCLK out only on GPIO0, 1 or 3"})
        if g["dac_mute"]:
            f.append(f"mute={g['dac_mute']['gpio']}:{g['dac_mute'].get('active', 0)}")
        if dac and "i2c" in dac.get("bus", ""):
            if not i2c:
                findings.append({"kind": "no_i2c", "ref": dac["ref"],
                                 "detail": f"{dac['part']} needs I2C and no SDA/SCL pins were found"})
            else:
                f += [f"sda={g['i2c_sda']['gpio']}", f"scl={g['i2c_scl']['gpio']}"]
                a = _i2c_addr(nl, dac, findings)
                if a is not None:
                    f.append(f"i2c={a}")
            ctl = dac.get("controls") or {}
            if not dac.get("verified") or not ctl.get("init"):
                findings.append({"kind": "codec_unverified", "ref": dac["ref"], "part": dac["part"],
                                 "detail": "its dac_controlset sequence is not checked against the "
                                           "datasheet (reference/esp32/codecs.json)"})
            cfg["dac_controlset"] = json.dumps(
                {k: [{"reg": r, "val": v} for r, v in ctl.get(k, [])]
                 for k in ("init", "poweron", "poweroff")}, separators=(",", ":"))
        cfg["dac_config"] = ",".join(f)
    elif dac:
        findings.append({"kind": "no_i2s", "ref": dac["ref"],
                         "detail": "an I2S sink is fitted but BCK/WS/DO pins were not all found"})

    gp = []
    for p in sorted(pins, key=lambda p: p["gpio"]):
        r = p["role"]
        if r == "amp_en":
            gp.append(f"{p['gpio']}=amp:{p.get('active', 1)}")
        elif r == "amp_fault":
            gp.append(f"{p['gpio']}=spkfault:{p.get('active', 0)}")
        elif r == "ir":
            gp.append(f"{p['gpio']}=ir")
        elif r == "jack":
            gp.append(f"{p['gpio']}=jack:0")
        elif r == "led_green":
            gp.append(f"{p['gpio']}=green:1")
        elif r == "led_red":
            gp.append(f"{p['gpio']}=red:1")
    if gp:
        cfg["set_GPIO"] = ",".join(gp)

    if g["enc_a"] and g["enc_b"]:
        cfg["rotary_config"] = f"A={g['enc_a']['gpio']},B={g['enc_b']['gpio']}" + (
            f",SW={g['enc_sw']['gpio']}" if g["enc_sw"] else "") + ",volume,longpress"

    phy = next((x for x in parts if x["kind"] == "phy"), None)
    if phy:
        if g["eth_mdc"] and g["eth_mdio"]:
            cfg["eth_config"] = f"model={phy['model']},mdc={g['eth_mdc']['gpio']},mdio={g['eth_mdio']['gpio']}" + (
                f",rst={g['eth_rst']['gpio']}" if g["eth_rst"] else "")
        else:
            findings.append({"kind": "no_mdio", "ref": phy["ref"], "detail": "MDC/MDIO pins not found"})
        for p in pins:
            want = RMII.get(p["gpio"])
            if want and p["role"] not in ("rmii", "unused") and p["role"] != "unclassified":
                findings.append({"kind": "rmii_pin_taken", "pin": p["pin"], "net": p["net"],
                                 "detail": f"the EMAC needs this pin for RMII {want}"})
            elif want and p["role"] == "rmii" and p.get("tag") != want:
                findings.append({"kind": "rmii_pin_swapped", "pin": p["pin"], "net": p["net"],
                                 "detail": f"the EMAC has RMII {want} fixed on this pin"})

    disp = next((x for x in parts if x["kind"] == "display"), None)
    if disp:
        w, h = DISPLAY_SIZE.get(disp["driver"], (128, 64))
        if g["disp_cs"]:
            if g["spi_mosi"] and g["spi_clk"]:
                cfg["spi_config"] = f"data={g['spi_mosi']['gpio']},clk={g['spi_clk']['gpio']}" + (
                    f",dc={g['disp_dc']['gpio']}" if g["disp_dc"] else "") + ",host=1"
            cfg["display_config"] = f"SPI,width={w},height={h},cs={g['disp_cs']['gpio']}" + (
                f",reset={g['disp_rst']['gpio']}" if g["disp_rst"] else "") + (
                f",back={g['disp_bl']['gpio']}" if g["disp_bl"] else "") + f",driver={disp['driver']}"
        elif i2c:
            cfg["display_config"] = f"I2C,width={w},height={h}" + (
                f",reset={g['disp_rst']['gpio']}" if g["disp_rst"] else "") + f",driver={disp['driver']}"
        else:
            findings.append({"kind": "display_bus", "ref": disp["ref"],
                             "detail": "neither a DISP_CS (SPI) nor an I2C bus reaches the display"})

    adc = next((x for x in parts if x["kind"] == "adc"), None)
    if adc:
        if g["i2s_di"] and g["i2s_bck"] and g["i2s_ws"]:
            fwe["linein_config"] = (f"model={adc['key']},bck={g['i2s_bck']['gpio']},"
                                    f"ws={g['i2s_ws']['gpio']},di={g['i2s_di']['gpio']}")
            if "i2c" in adc.get("bus", "") and i2c:
                a = _i2c_addr(nl, adc, findings)
                if a is not None:
                    fwe["linein_config"] += f",i2c={a}"
        else:
            findings.append({"kind": "no_i2s_in", "ref": adc["ref"],
                             "detail": "a line-in ADC is fitted but no I2S DIN pin was found"})
    warn = [p for p in pins if p["role"] == "amp_warn"]
    if warn:
        fwe["amp_warn_gpio"] = ",".join(f"{p['gpio']}:{p.get('active', 0)}" for p in warn)
    btn = [p for p in pins if p["role"] == "button"]
    if btn:
        fwe["buttons"] = ",".join(f"{p.get('tag', p['net']).lower()}={p['gpio']}" for p in btn)
    return cfg, fwe


def nvs_csv(namespaces: dict[str, dict[str, str]]) -> str:
    """The nvs_partition_gen.py CSV: one namespace row, then its string keys.
    NVS keys are at most 15 characters, so a longer one raises."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["key", "type", "encoding", "value"])
    for ns, keys in namespaces.items():
        if not keys:
            continue
        w.writerow([ns, "namespace", "", ""])
        for k, v in keys.items():
            if len(k) > 15:
                raise ValueError(f"NVS key {k!r} is longer than 15 characters")
            w.writerow([k, "data", "string", v])
    return buf.getvalue()


def header(m: dict) -> str:
    """gen/board_pins.h for our own components: one GPIO number per net."""
    out = ["/* board_pins.h - GENERATED by /fwe pinmap.py from "
           f"{m['workspace']}/{m['netlist']}.", " * Do not edit: regenerate with "
           "pinmap.py --workspace <board>; the build runs pinmap.py --check.",
           f" * netlist sha256 {m['netlist_sha256']} */",
           "#ifndef BOARD_PINS_H", "#define BOARD_PINS_H", "",
           f"#define BOARD_ID \"{m['board']}\"", f"#define BOARD_MCU \"{m['mcu']['part']}\"", ""]
    for p in m["pins"]:
        if p["role"] in ("unused", "unclassified"):
            continue
        n = "PIN_" + re.sub(r"[^A-Z0-9]", "_", p["net"].upper())
        out.append(f"#define {n}_GPIO {p['gpio']} /* {p['role']} */")
    out += ["", "#endif /* BOARD_PINS_H */", ""]
    return "\n".join(out)
