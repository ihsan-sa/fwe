#!/usr/bin/env python3
"""bringup_plan.py - write firmware/bringup-plan.json, the plan /npie carries out.

The plan (reference/manifest.md, "The bring-up plan", schema fwe-bringup-plan/1)
is derived from the manifest fw_manifest.py wrote, never hand-written, so it
names nothing the manifest doesn't. Its steps run in order, and /npie stops at
the first that fails and reports it back:

  power   the rails the test hooks need, current-limited, by a human
  flash   the manifest's flash commands over its connector
  boot    the console's banner, then the EVT boot line with the reset cause
  hook:*  each test hook, unattended, after the rails it needs
  cmd:*   each `safe: false` command, only after a human confirms it

Every step says what /npie sends back (`report`) and where /fwe looks first
when it fails (`fwe_suspects`), so the two can find the firmware side of an
issue without /fwe seeing the bench. An ESP32 manifest (fwe-esp32-manifest/1)
has no fwe console, so its plan is power, flash over the ROM bootloader with
its boot strap, boot (the ROM's reset line on upstream's console), one nvs:*
step per setting read back against the manifest, one st:* step per fwe_selftest
command once its `selftest` section is `ready` (all but `st tone`, whose taps
the manifest doesn't name), then its test hooks if any.

  bringup_plan.py --workspace PCB-0018-A_bldc-motor-driver

JSON to stdout (or --out): {"ok", "path", "plan"}. Exit 0 written, 1 no
manifest (run fw_manifest.py first), 2 error (a manifest this can't plan).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

SCHEMA = "fwe-bringup-plan/1"
NAME = "bringup-plan.json"
MANIFEST = "fwe-manifest.json"
REPORT = ["the step id", "every console line seen, verbatim", "the bench supply's current"]


class Error(Exception):
    pass


def _power(man: dict) -> dict:
    rails = sorted({r for h in man.get("test_hooks", []) for r in h.get("needs", [])})
    s = man.get("safety", {})
    do = "power the board from a current-limited supply"
    if "vbus_uv_v" in s and "vbus_ov_v" in s:
        do += f", VBUS between {s['vbus_uv_v']} and {s['vbus_ov_v']} V"
    return {"id": "power", "kind": "human", "do": do, "rails": rails,
            "expect": "every rail in range, no current beyond the MCU's idle draw",
            "fwe_suspects": ["nothing yet: a rail out of range is hardware, a finding for hwde"]}


def _flash(man: dict) -> dict:
    f, a = man["flash"], man["artifact"]
    return {"id": "flash", "kind": "unattended", "interface": f["interface"],
            "connector": f["connector"], "commands": f["commands"], "sha256": a["sha256"],
            "expect": "the probe finds the part, writes and verifies the image",
            "fwe_suspects": [f"the probe's chip name for {man['mcu']['part']} in the flash commands",
                             "the option bytes (BOOT0, read protection) the firmware sets"]}


def _boot(man: dict) -> dict:
    u = man["uart"]
    return {"id": "boot", "kind": "unattended", "connector": u["connector"],
            "uart": {k: u[k] for k in ("tx_pin", "rx_pin", "baud", "format", "levels")},
            "expect": [u["banner_regex"], '^EVT \\{"boot":'], "timeout_s": 5,
            "fwe_suspects": ["the clock tree (HSE start-up, PLL) in the stage's clock setup",
                             f"the UART pins and baud in gen/board_pins.h ({u['baud']} baud)",
                             "a fault handler before the banner (report the EVT reset cause)"]}


def _hook(h: dict) -> dict:
    verb = h["send"].split()
    if not verb:
        raise Error(f"test hook {h['name']!r} sends nothing")
    return {"id": f"hook:{h['name']}", "kind": "unattended", "send": h["send"],
            "expect": h["expect"], "timeout_s": h["timeout_s"], "needs": h.get("needs", []),
            "fwe_suspects": [f"the console handler for `{verb[0]}`"]}


def _confirm(c: dict, safety: dict) -> dict:
    return {"id": f"cmd:{c['name']}", "kind": "confirm", "send": c["name"], "args": c["args"],
            "expect": "^OK ", "limits": safety,
            "do": "a human confirms the bench is ready to be energised before /npie sends it",
            "fwe_suspects": [f"the console handler for `{c['name']}` and the limits it enforces"]}


def _esp32_flash(man: dict) -> dict:
    f = man["flash"]
    return {"id": "flash", "kind": "unattended", "interface": f["interface"],
            "boot_strap": f["boot_strap"], "uart": {"tx_gpio": f["tx_gpio"], "rx_gpio": f["rx_gpio"]},
            "command": f["command"], "sha256": {i["name"]: i["sha256"] for i in man["images"]},
            "expect": "esptool connects to the ROM bootloader, writes and verifies every image",
            "fwe_suspects": ["the flash mode, frequency and size in the esptool command against "
                             f"the {man['mcu']['part']}",
                             "an image's offset against upstream's partition table",
                             "a strap or auto-reset circuit that misses the boot strap is hardware, "
                             "a finding for hwde"]}


def _esp32_boot(man: dict) -> dict:
    c = man["console"]
    return {"id": "boot", "kind": "unattended",
            "uart": {k: c[k] for k in ("tx_gpio", "rx_gpio", "baud", "format", "levels")},
            "expect": [r"^rst:0x[0-9a-f]+ \(", r"^I \(\d+\) "], "timeout_s": 10,
            "fwe_suspects": ["a boot strap still held: boot:0x3 in the rst line is download mode",
                             f"the PSRAM setting against the module ({man['mcu'].get('psram_mb')} MB)",
                             "the bootloader or partition table image (report the rst line verbatim)"]}


def _nvs(man: dict) -> list[dict]:
    nvs = man["nvs"]
    return [{"id": f"nvs:{ns}.{key}", "kind": "unattended", "partition": nvs["partition"],
             "namespace": ns, "key": key, "expect": value,
             "do": "read the key back over upstream's console and compare it verbatim",
             "fwe_suspects": [f"the {ns}.{key} row of {nvs['csv']}, which pinmap.py wrote",
                              "the nvs_config image's offset against the settings partition"]}
            for ns, keys in nvs["namespaces"].items() for key, value in keys.items()]


# Where /fwe looks first when an `st` line fails, beyond the handler itself.
ST_SUSPECTS = {"rails": "the rail ADC channels and scales in gen/board_pins.h",
               "pd": "the CH224A's I2C address and register read in fwe_pd_limit's glue",
               "net": "the network upstream brought up, before the TCP listener started"}


def _selftest(man: dict) -> list[dict]:
    st = man.get("selftest")
    if not st or not st.get("ready"):
        return []
    return [{"id": f"st:{c['name']}", "kind": "unattended", "send": c["send"],
             "expect": st["answer"]["ok"], "timeout_s": 5,
             "fwe_suspects": [f"fwe_selftest's `{c['name']}` handler and the JSON it writes",
                              ST_SUSPECTS.get(c["name"], "the board's ops in the selftest glue")]}
            for c in st["commands"] if "args" not in c]


def plan(man: dict) -> dict:
    if not isinstance(man, dict):
        raise Error(f"manifest is a JSON {type(man).__name__}, not an object")
    schema = man.get("schema")
    if schema not in ("fwe-manifest/1", "fwe-esp32-manifest/1"):
        raise Error(f"can't plan a {schema!r} manifest: only fwe-manifest/1 and fwe-esp32-manifest/1")
    try:
        board = man["board"]
        if schema == "fwe-esp32-manifest/1":
            steps = [_power(man), _esp32_flash(man), _esp32_boot(man)] + _nvs(man) + _selftest(man)
        else:
            steps = [_power(man), _flash(man), _boot(man)]
        steps += [_hook(h) for h in man.get("test_hooks", [])]
        steps += [_confirm(c, man.get("safety", {})) for c in man.get("commands", []) if not c["safe"]]
    except KeyError as e:
        raise Error(f"manifest has no {e}") from e
    return {"schema": SCHEMA, "board": board, "stage": man.get("stage"),
            "version": man.get("version"), "verified": man.get("verified", {}),
            "on_fail": {"stop": True, "report": REPORT}, "steps": steps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    fw = fwenv.workspace(a.workspace) / "firmware"
    src = fw / MANIFEST
    if not src.is_file():
        fwenv.emit({"ok": False, "error": f"no {src}: run fw_manifest.py first"}, a.out)
        return 1
    try:
        p = plan(json.loads(src.read_text(encoding="utf-8")))
    except (Error, ValueError) as e:
        fwenv.emit({"ok": False, "error": str(e)}, a.out)
        return 2
    path = fw / NAME
    path.write_text(json.dumps(p, indent=2) + "\n", encoding="utf-8")
    fwenv.emit({"ok": True, "path": str(path), "plan": p}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
