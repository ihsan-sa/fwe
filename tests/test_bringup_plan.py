"""/fwe's bring-up plan for /npie, derived from a fixture manifest.

The manifest is manifest.md's example, written by hand into tmp_path, so the
plan is checked without a board, a toolchain or a build.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import bringup_plan  # noqa: E402
import bringup_triage  # noqa: E402
import task_router  # noqa: E402

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
    rc, res = _run(tmp_path / "b", {**MANIFEST, "schema": "fwe-manifest/9"})
    assert rc == 2 and "fwe-manifest/9" in res["error"]
    rc, res = _run(tmp_path / "c", {k: v for k, v in MANIFEST.items() if k != "uart"})
    assert rc == 2 and "uart" in res["error"]
    rc, res = _run(tmp_path / "d", {k: v for k, v in MANIFEST.items() if k != "board"})
    assert rc == 2 and "board" in res["error"]
    rc, res = _run(tmp_path / "e", [MANIFEST])
    assert rc == 2 and "not an object" in res["error"]
    hooks = [{**MANIFEST["test_hooks"][0], "send": " "}]
    rc, res = _run(tmp_path / "f", {**MANIFEST, "test_hooks": hooks})
    assert rc == 2 and "sends nothing" in res["error"]


def test_plan_without_safety_or_test_hooks(tmp_path):
    rc, res = _run(tmp_path / "a", {k: v for k, v in MANIFEST.items() if k != "safety"})
    assert rc == 0
    steps = res["plan"]["steps"]
    assert "VBUS" not in steps[0]["do"]
    assert [s["limits"] for s in steps if s["kind"] == "confirm"] == [{}, {}]
    rc, res = _run(tmp_path / "b", {k: v for k, v in MANIFEST.items() if k != "test_hooks"})
    assert rc == 0
    steps = res["plan"]["steps"]
    assert [s["id"] for s in steps] == ["power", "flash", "boot", "cmd:arm", "cmd:duty"]
    assert steps[0]["rails"] == []


ESP32 = {
    "schema": "fwe-esp32-manifest/1", "board": "PCB-0029-A",
    "mcu": {"part": "ESP32-WROVER-E-N8R8", "core": "xtensa-lx6", "chip": "esp32",
            "flash_mb": 8, "psram_mb": 8},
    "firmware": {"base": "squeezelite-esp32", "esp_idf": "v4.4.8", "platform": "I2S-4MFlash"},
    "images": [{"name": "bootloader", "offset": "0x1000", "file": "build/bootloader/bootloader.bin",
                "sha256": "b1"},
               {"name": "nvs_config", "offset": "0x9000", "file": "build/nvs_config.bin",
                "sha256": "n1"}],
    "flash": {"interface": "uart-rom-bootloader", "tx_gpio": 1, "rx_gpio": 3, "baud": 460800,
              "boot_strap": "GPIO0 low at reset",
              "command": ["esptool.py", "--chip", "esp32", "write_flash", "0x1000", "build/b.bin"]},
    "console": {"tx_gpio": 1, "rx_gpio": 3, "baud": 115200, "format": "8N1", "levels": "3V3",
                "commands": "upstream squeezelite-esp32's own console"},
    "nvs": {"csv": "gen/nvs_config.csv", "partition": "settings",
            "namespaces": {"config": {"dac_config": "model=I2S,bck=33,ws=26,do=25",
                                      "dac_controlset": "{}"},
                           "fwe": {}}},
    "commands": [], "test_hooks": [],
    "verified": {"build": True, "host_tests": False, "hardware": False},
}


def test_esp32_plan_flashes_over_the_rom_then_reads_back_nvs(tmp_path):
    rc, res = _run(tmp_path, ESP32)
    assert rc == 0 and res["ok"]
    plan = res["plan"]
    assert plan["board"] == "PCB-0029-A" and plan["verified"]["host_tests"] is False
    assert [s["id"] for s in plan["steps"]] == [
        "power", "flash", "boot", "nvs:config.dac_config", "nvs:config.dac_controlset"]
    power, flash, boot, dac = plan["steps"][:4]
    assert power["kind"] == "human" and power["rails"] == []
    assert flash["boot_strap"] == "GPIO0 low at reset" and flash["command"][0] == "esptool.py"
    assert flash["sha256"] == {"bootloader": "b1", "nvs_config": "n1"}
    assert boot["uart"]["baud"] == 115200
    assert re.search(boot["expect"][0], "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)")
    assert re.search(boot["expect"][1], "I (29) boot: ESP-IDF v4.4.8 2nd stage bootloader")
    assert dac["namespace"] == "config" and dac["expect"] == "model=I2S,bck=33,ws=26,do=25"
    assert all(s["kind"] in ("human", "unattended") and s["fwe_suspects"] for s in plan["steps"])


def test_esp32_plan_takes_its_test_hooks_and_refuses_a_manifest_without_nvs(tmp_path):
    hook = {"name": "pd", "send": "st pd", "expect": "^OK ", "timeout_s": 5, "needs": ["VBUS"]}
    rc, res = _run(tmp_path / "a", {**ESP32, "test_hooks": [hook]})
    assert rc == 0
    steps = res["plan"]["steps"]
    assert steps[-1]["id"] == "hook:pd" and steps[0]["rails"] == ["VBUS"]
    rc, res = _run(tmp_path / "b", {k: v for k, v in ESP32.items() if k != "nvs"})
    assert rc == 2 and "nvs" in res["error"]


SELFTEST = {"protocol": "npie-selftest/1", "component": "fwe_selftest",
            "commands": [{"name": "rails", "send": "st rails"}, {"name": "pd", "send": "st pd"},
                         {"name": "tone", "send": "st tone <tap> <hz> <dBFS>",
                          "args": {"tap": "^[A-Za-z0-9_]{1,15}$", "hz": [20, 20000],
                                   "dbfs": [-60.0, 0.0]}},
                         {"name": "net", "send": "st net"}],
            "answer": {"ok": "^OK \\{", "err": "^ERR "}, "ready": True}


def test_esp32_plan_runs_the_selftest_only_once_it_is_ready(tmp_path):
    rc, res = _run(tmp_path / "a", {**ESP32, "selftest": {**SELFTEST, "ready": False}})
    assert rc == 0 and not any(s["id"].startswith("st:") for s in res["plan"]["steps"])
    rc, res = _run(tmp_path / "b", {**ESP32, "selftest": SELFTEST})
    assert rc == 0
    steps = res["plan"]["steps"]
    assert [s["id"] for s in steps][-3:] == ["st:rails", "st:pd", "st:net"]
    pd = steps[-2]
    assert pd["send"] == "st pd" and pd["kind"] == "unattended" and len(pd["fwe_suspects"]) == 2
    assert re.search(pd["expect"], 'OK {"contract_v":20}')
    assert not re.search(pd["expect"], "ERR no PD contract")
    report = {"schema": bringup_triage.REPORT, "board": "PCB-0029-A", "step": "st:pd",
              "lines": ["ERR no PD contract"], "current_a": 0.1}
    t = bringup_triage.triage(res["plan"], report)
    assert t["side"] == "firmware" and "no PD contract" in t["findings"][0]["suspect"]
    t = bringup_triage.triage(res["plan"], {**report, "lines": []})
    assert "never answered `st pd`" in t["findings"][0]["suspect"]


def test_esp32_plan_plays_st_tone_once_per_tap(tmp_path):
    tone = {**SELFTEST["commands"][2], "taps": [{"tap": "VINL1", "net": "DAC_OUTL"},
                                                {"tap": "VINR1", "net": "DAC_OUTR"}]}
    cmds = SELFTEST["commands"][:2] + [tone] + SELFTEST["commands"][3:]
    rc, res = _run(tmp_path, {**ESP32, "selftest": {**SELFTEST, "commands": cmds}})
    assert rc == 0
    steps = res["plan"]["steps"]
    assert [s["id"] for s in steps][-5:] == ["st:rails", "st:pd", "st:tone.VINL1", "st:tone.VINR1", "st:net"]
    left = steps[-3]
    assert left["send"] == "st tone VINL1 1000 -20" and re.search(left["expect"], 'OK {"thd_pct":0.01}')
    assert "DAC_OUTL" in left["fwe_suspects"][1]
    report = {"schema": bringup_triage.REPORT, "board": "PCB-0029-A", "step": "st:tone.VINL1",
              "lines": ["ERR no signal"], "current_a": 0.2}
    t = bringup_triage.triage(res["plan"], report)
    assert t["side"] == "firmware" and "no signal" in t["findings"][0]["suspect"]
    assert any("DAC_OUTL" in f["suspect"] for f in t["findings"])


@pytest.mark.parametrize("task,verb", [
    ("write the bring-up plan", "bringup"),
    ("plan the bringup", "bringup"),
    ("write the esp32 bring-up plan", "esp32-bringup"),
    ("plan bring-up for the squeezelite board", "esp32-bringup"),
])
def test_router_picks_the_bringup_verb(task, verb):
    assert task_router.match(task) == [verb]


@pytest.mark.parametrize("verb,manifest", [
    ("bringup", "fw_manifest.py"), ("esp32-bringup", "esp32_manifest.py"), ("full-run", "fw_manifest.py")])
def test_router_writes_the_manifest_then_the_plan(tmp_path, verb, manifest):
    rc = task_router.main(["--verb", verb, "--workspace", str(tmp_path), "--out", str(tmp_path / "o.json")])
    res = json.loads((tmp_path / "o.json").read_text())
    assert rc == 0 and Path(res["doc"]).is_file()
    cmds = [s["cmd"].split()[1] for s in res["steps"] if s["kind"] == "script"]
    assert Path(cmds[-1]).name == "bringup_plan.py" and Path(cmds[-2]).name == manifest
    assert res["steps"][-1]["cmd"].endswith(f"bringup_plan.py --workspace {tmp_path}")
