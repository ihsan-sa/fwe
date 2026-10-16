#!/usr/bin/env python3
"""esp32_manifest.py - write or check firmware/fwe-manifest.json for an ESP32 board.

The manifest is what /npie reads to flash a squeezelite-esp32 board
(reference/manifest.md, "ESP32 boards", schema `fwe-esp32-manifest/1`):
the module from the pin map, the upstream commit and ESP-IDF it was built
on, every image with its flash offset and sha256 (the NVS settings image
last), the esptool command that writes them, and the NVS settings
themselves so /npie can say what the board was configured as. It derives
nothing about a bench. `verified` is evidence: `build` is whether
build/fwe_build.json passed for the images on disk and today's
gen/nvs_config.csv, `host_tests` whether build/fwe_host_tests.json passed on
today's components and tests, `hardware` always false.

  esp32_manifest.py --workspace PCB-0029-A_hifi-lite [--check]

JSON to stdout (or --out): {"ok", "manifest", "stale"?}. Exit 0 written (or
--check: current), 1 --check found it stale or absent, 2 error (no pin map
or no build).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, squeezelite, upstream  # noqa: E402
from esp32_test import inputs_hash  # noqa: E402

SCHEMA = "fwe-esp32-manifest/1"
FLASH_BAUD = 460800
CONSOLE_BAUD = 115200   # ESP-IDF's console default, which upstream keeps


def _json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def module(part: str) -> dict:
    """Flash and PSRAM size from an Espressif module's ordering code (…-N8R8)."""
    m = re.search(r"-N(\d+)(?:R(\d+))?$", part.upper())
    return {"part": part, "core": "xtensa-lx6", "chip": "esp32",
            "flash_mb": int(m.group(1)) if m else None,
            "psram_mb": int(m.group(2)) if m and m.group(2) else 0 if m else None}


def selftest(fw: Path, taps: list[dict]) -> dict | None:
    """The fwe_selftest console's commands, `st tone`'s ranges as its header defines them
    and its taps (the line-in ADC's wired mux inputs) as the pin map found them.

    `ready` is whether the component has more than core/ (the handlers and the
    USB serial/TCP glue); /npie runs no `st` line while it is false.
    """
    comp = fw / "components" / "fwe_selftest"
    try:
        h = (comp / "include" / "fwe_selftest.h").read_text()
    except OSError:
        return None
    d = {k: float(v) for k, v in re.findall(r"#define FWE_ST_(\w+) \(?(-?[\d.]+)\)?", h)}
    return {
        "protocol": "npie-selftest/1", "component": "fwe_selftest",
        "commands": [
            {"name": "rails", "send": "st rails"},
            {"name": "pd", "send": "st pd"},
            {"name": "tone", "send": "st tone <tap> <hz> <dBFS>",
             "args": {"tap": f"^[A-Za-z0-9_]{{1,{int(d['TAP_MAX'])}}}$",
                      "hz": [int(d["TONE_MIN_HZ"]), int(d["TONE_MAX_HZ"])],
                      "dbfs": [d["TONE_MIN_DBFS"], 0.0]},
             "taps": [{"tap": t["tap"], "net": t["net"]} for t in taps]},
            {"name": "net", "send": "st net"},
        ],
        "answer": {"ok": r"^OK \{", "err": "^ERR "},
        "ready": any(p.suffix == ".c" and "core" not in p.relative_to(comp).parts
                     for p in comp.rglob("*.c")),
    }


def derive(fw: Path) -> tuple[dict | None, str | None]:
    pm = _json(fw / "pinmap.json")
    if not pm:
        return None, "no firmware/pinmap.json: run pinmap.py"
    if squeezelite.later_series(pm["mcu"]["part"]):
        return None, f"{pm['mcu']['part']} is not a classic ESP32: no xtensa-lx6 manifest for it"
    b = _json(fw / "build" / "fwe_build.json")
    if not b or not b.get("artifacts"):
        return None, "no firmware/build/fwe_build.json with images: run esp32_build.py"
    images, build_ok = [], bool(b.get("ok"))
    for off, rel in b.get("flash", []):
        path, a = fw / "build" / rel, b["artifacts"].get(rel)
        sha = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        build_ok = build_ok and sha is not None and a is not None and sha == a["sha256"]
        images.append({"name": Path(rel).stem, "offset": off, "file": f"build/{rel}", "sha256": sha})
    csv_file = fw / "gen" / "nvs_config.csv"
    csv_sha = hashlib.sha256(csv_file.read_bytes()).hexdigest() if csv_file.is_file() else None
    build_ok = build_ok and b.get("nvs_csv_sha256") == csv_sha    # the image holds today's settings
    ht = _json(fw / "build" / "fwe_host_tests.json")
    ht_ok = bool(ht and ht.get("ok") and ht.get("inputs_sha256") == inputs_hash(fw))
    u = upstream.entry()
    idf = fwenv.framework("esp-idf")
    man = {
        "schema": SCHEMA,
        "board": pm["board"],
        "mcu": module(pm["mcu"]["part"]),
        "firmware": {"base": upstream.NAME, "upstream_commit": b.get("upstream", {}).get("commit"),
                     "pinned_commit": u["commit"], "esp_idf": idf["version"],
                     "platform": b.get("platform")},
        "images": images,
        "flash": {
            "interface": "uart-rom-bootloader", "tx_gpio": 1, "rx_gpio": 3, "baud": FLASH_BAUD,
            "boot_strap": "GPIO0 low at reset",
            "command": ["esptool.py", "--chip", "esp32", "-b", str(FLASH_BAUD), "write_flash", "-z",
                        *b.get("flash_options", [])]
                       + [x for i in images for x in (i["offset"], i["file"])],
        },
        "console": {"tx_gpio": 1, "rx_gpio": 3, "baud": CONSOLE_BAUD, "format": "8N1",
                    "levels": "3V3", "commands": "upstream squeezelite-esp32's own console"},
        "nvs": {"csv": "gen/nvs_config.csv", "partition": "settings",
                "namespaces": pm.get("squeezelite", {})},
        "commands": [],
        "test_hooks": [],
        **({"selftest": st} if (st := selftest(fw, pm.get("tone_taps", []))) else {}),
        "verified": {"build": build_ok, "host_tests": ht_ok, "hardware": False},
    }
    return man, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if stale or absent")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    fw = fwenv.workspace(a.workspace) / "firmware"
    man, err = derive(fw) if fw.is_dir() else (None, f"no {fw}")
    path = fw / "fwe-manifest.json"
    if err:
        rc, res = 2, {"ok": False, "error": err}
    elif a.check:
        stale = _json(path) != man
        rc, res = (1 if stale else 0), {"ok": not stale, "manifest": str(path), "stale": stale}
    else:
        path.write_text(json.dumps(man, indent=2) + "\n")
        rc, res = 0, {"ok": True, "manifest": str(path)}
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
