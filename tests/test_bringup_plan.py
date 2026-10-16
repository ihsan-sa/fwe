"""/fwe's bring-up plan for /npie, derived from a fixture manifest.

The manifest is manifest.md's example, written by hand into tmp_path, so the
plan is checked without a board, a toolchain or a build.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import bringup_plan  # noqa: E402

MANIFEST = {
    "schema": "fwe-manifest/1", "board": "PCB-0018-A",
    "mcu": {"part": "STM32G431CBT6", "core": "cortex-m4", "flash_base": "0x08000000"},
    "stage": "bringup", "version": "0.1.0+gabc",
    "artifact": {"elf": "build/fw.elf", "sha256": {"elf": "e1"}},
    "flash": {"interface": "swd", "connector": "J601",
              "commands": {"probe-rs": ["probe-rs", "download", "--chip", "STM32G431CBTx", "{elf}"]}},
    "uart": {"connector": "J701", "tx_pin": "3", "rx_pin": "4", "baud": 115200,
             "format": "8N1", "levels": "3V3", "banner_regex": "^fwe PCB-0018-A "},
    "commands": [{"name": "status", "args": "", "safe": True},
                 {"name": "arm", "args": "", "safe": False},
                 {"name": "duty", "args": "<a> <b> <c>", "safe": False}],
    "test_hooks": [{"name": "version", "send": "version", "expect": "^OK ", "timeout_s": 5,
                    "needs": ["+3V3"]},
                   {"name": "adc", "send": "adc", "expect": "^OK ", "timeout_s": 5,
                    "needs": ["+3V3", "VBUS"]}],
    "safety": {"vbus_ov_v": 30.0, "vbus_uv_v": 9.0, "max_duty": 0.95},
    "verified": {"build": True, "host_tests": True, "sim": None, "hardware": False},
}


def _run(tmp_path, man: dict | None) -> tuple[int, dict]:
    fw = tmp_path / "PCB-0018-A_bldc" / "firmware"
    fw.mkdir(parents=True)
    if man is not None:
        (fw / "fwe-manifest.json").write_text(json.dumps(man))
    out = tmp_path / "out.json"
    rc = bringup_plan.main(["--workspace", str(fw.parent), "--out", str(out)])
    return rc, json.loads(out.read_text())


def test_plan_orders_power_flash_boot_hooks_then_confirmed_commands(tmp_path):
    rc, res = _run(tmp_path, MANIFEST)
    assert rc == 0 and res["ok"]
    plan = res["plan"]
    assert json.loads(Path(res["path"]).read_text()) == plan
    assert plan["schema"] == "fwe-bringup-plan/1" and plan["board"] == "PCB-0018-A"
    assert [s["id"] for s in plan["steps"]] == [
        "power", "flash", "boot", "hook:version", "hook:adc", "cmd:arm", "cmd:duty"]
    power, flash, boot = plan["steps"][:3]
    assert power["kind"] == "human" and power["rails"] == ["+3V3", "VBUS"]
    assert "between 9.0 and 30.0 V" in power["do"]
    assert flash["connector"] == "J601" and flash["sha256"] == {"elf": "e1"}
    assert boot["expect"][0] == "^fwe PCB-0018-A " and boot["uart"]["baud"] == 115200
    assert all(s["kind"] == "unattended" for s in plan["steps"][1:5])
    arm, duty = plan["steps"][5:]
    assert arm["kind"] == duty["kind"] == "confirm"
    assert duty["args"] == "<a> <b> <c>" and duty["limits"]["max_duty"] == 0.95
    assert all(s["fwe_suspects"] for s in plan["steps"])
    assert plan["on_fail"]["stop"] is True


def test_plan_needs_a_manifest_and_refuses_one_it_cannot_plan(tmp_path):
    rc, res = _run(tmp_path / "a", None)
    assert rc == 1 and "fw_manifest.py" in res["error"]
    rc, res = _run(tmp_path / "b", {**MANIFEST, "schema": "fwe-esp32-manifest/1"})
    assert rc == 2 and "fwe-esp32-manifest/1" in res["error"]
    rc, res = _run(tmp_path / "c", {k: v for k, v in MANIFEST.items() if k != "uart"})
    assert rc == 2 and "uart" in res["error"]
