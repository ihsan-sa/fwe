"""/fwe's triage of /npie's report on a failed bring-up step.

The plans come from test_bringup_plan's fixture manifests through
bringup_plan.plan, and the reports are written by hand with the console lines
a real board prints, so the triage is checked without a bench.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bringup_plan  # noqa: E402
import bringup_triage  # noqa: E402
import pytest  # noqa: E402
import task_router  # noqa: E402
from test_bringup_plan import ESP32, MANIFEST  # noqa: E402


def _run(tmp_path, man: dict | None, step: str, lines: list, **extra) -> tuple[int, dict]:
    fw = tmp_path / "ws" / "firmware"
    fw.mkdir(parents=True)
    if man is not None:
        (fw / "bringup-plan.json").write_text(json.dumps(bringup_plan.plan(man)))
    rep = {"schema": "fwe-bringup-report/1", "board": (man or MANIFEST)["board"], "step": step,
           "lines": lines, "current_a": 0.05, **extra}
    (tmp_path / "rep.json").write_text(json.dumps(rep))
    out = tmp_path / "out.json"
    rc = bringup_triage.main(["--workspace", str(fw.parent), "--report", str(tmp_path / "rep.json"),
                              "--out", str(out)])
    return rc, json.loads(out.read_text())


def test_esp32_boot_in_download_mode_is_a_strap_for_hwde(tmp_path):
    rst = "rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))"
    rc, res = _run(tmp_path, ESP32, "boot", [rst, "waiting for download"])
    assert rc == 0 and res["ok"]
    t = res["triage"]
    assert json.loads(Path(res["path"]).read_text()) == t
    assert t["schema"] == "fwe-bringup-triage/1" and t["step"] == "boot" and t["rerun_from"] == "boot"
    assert t["side"] == "hardware" and t["findings"][0]["evidence"] == rst
    assert "GPIO0" in t["findings"][0]["suspect"] and t["current_a"] == 0.05
    plan_suspects = [f["suspect"] for f in t["findings"] if f["evidence"] is None]
    assert plan_suspects[0].startswith("a boot strap still held")


def test_esp32_crash_and_brownout_point_at_their_side(tmp_path):
    lines = ["rst:0xc (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)",
             "Guru Meditation Error: Core  0 panic'ed (LoadProhibited).",
             "Backtrace:0x400d1234:0x3ffb1230"]
    rc, res = _run(tmp_path / "a", ESP32, "boot", lines)
    assert rc == 0 and res["triage"]["side"] == "firmware"
    assert [f["evidence"] for f in res["triage"]["findings"][:2]] == lines[1:]
    rc, res = _run(tmp_path / "b", ESP32, "nvs:config.dac_config", ["Brownout detector was triggered"])
    assert res["triage"]["side"] == "hardware" and "3V3" in res["triage"]["findings"][0]["suspect"]


def test_esp32_nvs_readback_that_differs_names_the_row(tmp_path):
    rc, res = _run(tmp_path / "a", ESP32, "nvs:config.dac_config", ["model=I2S,bck=26,ws=33,do=25"])
    f = res["triage"]["findings"][0]
    assert rc == 0 and f["side"] == "firmware" and "config.dac_config row" in f["suspect"]
    rc, res = _run(tmp_path / "b", ESP32, "nvs:config.dac_config", [])
    assert "missing" in res["triage"]["findings"][0]["suspect"]


def test_mcu_boot_banner_without_boot_line_and_watchdog_resets(tmp_path):
    rc, res = _run(tmp_path / "a", MANIFEST, "boot", ["fwe PCB-0018-A 0.1.0+gabc"])
    assert rc == 0 and "console_boot()" in res["triage"]["findings"][0]["suspect"]
    evt = 'EVT {"boot":{"reset_cause":"iwdg"}}'
    rc, res = _run(tmp_path / "b", MANIFEST, "boot", ["fwe PCB-0018-A 0.1.0+gabc", evt])
    assert res["triage"]["findings"][0] == {
        "side": "firmware", "evidence": evt,
        "suspect": "the watchdog fires before init feeds it: a stall in the clock or ADC setup"}
    rc, res = _run(tmp_path / "c", MANIFEST, "boot", [])
    assert "nothing on the console" in res["triage"]["findings"][0]["suspect"]


def test_mcu_hook_error_and_silence_name_the_handler(tmp_path):
    rc, res = _run(tmp_path / "a", MANIFEST, "hook:adc", ["ERR adc conversion timeout"])
    assert rc == 0 and res["triage"]["findings"][0]["suspect"] == "the console handler's `adc` error for `adc`"
    rc, res = _run(tmp_path / "b", MANIFEST, "cmd:arm", [])
    assert res["triage"]["findings"][0]["suspect"] == "the console handler for `arm` never answered"


def test_flash_and_power_failures_off_the_firmware_side(tmp_path):
    rc, res = _run(tmp_path / "a", ESP32, "flash",
                   ["A fatal error occurred: Failed to connect to ESP32: No serial data received."])
    assert rc == 0 and res["triage"]["side"] == "hardware"
    rc, res = _run(tmp_path / "b", MANIFEST, "flash", ["Error: No probe was found."])
    assert res["triage"]["side"] == "bench"
    rc, res = _run(tmp_path / "c", MANIFEST, "power", [])
    assert res["triage"]["side"] == "hardware"


def test_triage_needs_a_plan_and_refuses_a_report_it_cannot_read(tmp_path):
    rc, res = _run(tmp_path / "a", None, "boot", [])
    assert rc == 1 and "bringup_plan.py" in res["error"]
    rc, res = _run(tmp_path / "b", MANIFEST, "hook:nope", [])
    assert rc == 2 and "no step 'hook:nope'" in res["error"]
    rc, res = _run(tmp_path / "c", MANIFEST, "boot", [], schema="fwe-bringup-report/9")
    assert rc == 2 and "fwe-bringup-report/9" in res["error"]
    rc, res = _run(tmp_path / "d", MANIFEST, "boot", [], board="PCB-0099-A")
    assert rc == 2 and "PCB-0099-A" in res["error"]
    rc, res = _run(tmp_path / "e", MANIFEST, "boot", "fwe PCB-0018-A")
    assert rc == 2 and "list of strings" in res["error"]


def test_each_triage_is_logged_until_its_fix_is_recorded(tmp_path):
    rc, res = _run(tmp_path, MANIFEST, "boot", ['EVT {"boot":{"reset_cause":"iwdg"}}'])
    ws, fw = str(tmp_path / "ws"), tmp_path / "ws" / "firmware"
    assert rc == 0 and res["issue"]["n"] == 1 and res["issue"]["fix"] is None
    assert res["issue"]["side"] == "firmware" and "watchdog" in res["issue"]["suspect"]
    out = tmp_path / "o.json"
    assert bringup_triage.main(["--workspace", ws, "--report", str(tmp_path / "rep.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["issue"]["n"] == 1
    (tmp_path / "rep.json").write_text(json.dumps({"schema": "fwe-bringup-report/1", "board": MANIFEST["board"],
                                                   "step": "hook:adc", "lines": ["ERR busy"], "current_a": 0.05}))
    assert bringup_triage.main(["--workspace", ws, "--report", str(tmp_path / "rep.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["issue"]["n"] == 2
    assert bringup_triage.main(["--workspace", ws, "--fix", "1", "feed the IWDG before the ADC calibration",
                                "--out", str(out)]) == 0
    assert json.loads(out.read_text())["issue"]["fix"] == "feed the IWDG before the ADC calibration"
    assert bringup_triage.main(["--workspace", ws, "--open", "--out", str(out)]) == 0
    assert [i["n"] for i in json.loads(out.read_text())["open"]] == [2]
    log = json.loads((fw / "bringup-log.json").read_text())
    assert log["schema"] == "fwe-bringup-log/1" and log["board"] == MANIFEST["board"] and len(log["issues"]) == 2
    assert bringup_triage.main(["--workspace", ws, "--fix", "7", "x", "--out", str(out)]) == 2
    assert "no issue 7" in json.loads(out.read_text())["error"]
    assert json.loads((fw / "bringup-log.json").read_text()) == log


@pytest.mark.parametrize("task", ["triage the failed boot step", "triage the esp32 bring-up report"])
def test_router_picks_triage_for_mcu_and_esp32_tasks(task):
    assert task_router.match(task) == ["triage"]


@pytest.mark.parametrize("man,step,lines,side", [
    (MANIFEST, "boot", ['EVT {"boot":{"reset_cause":"wwdg"}}'], "firmware"),
    (ESP32, "boot", ["rst:0x1 (POWERON_RESET),boot:0x3 (DOWNLOAD_BOOT(UART0/UART1/SDIO_REI_REO_V2))"], "hardware")])
def test_router_runs_the_triage_on_an_stm32_and_an_esp32(tmp_path, man, step, lines, side):
    fw = tmp_path / "ws" / "firmware"
    fw.mkdir(parents=True)
    (fw / "bringup-plan.json").write_text(json.dumps(bringup_plan.plan(man)))
    (fw / "bringup-report.json").write_text(json.dumps(
        {"schema": "fwe-bringup-report/1", "board": man["board"], "step": step, "lines": lines, "current_a": 0.05}))
    out = tmp_path / "o.json"
    assert task_router.main(["--verb", "triage", "--workspace", str(fw.parent), "--out", str(out)]) == 0
    res = json.loads(out.read_text())
    assert Path(res["doc"]).is_file() and [s["kind"] for s in res["steps"]] == ["script"]
    script, *args = res["steps"][0]["cmd"].split()[1:]
    assert Path(script).name == "bringup_triage.py"
    assert bringup_triage.main(args) == 0
    t = json.loads((fw / "bringup-triage.json").read_text())
    assert t["step"] == step and t["side"] == side and t["findings"][0]["evidence"] == lines[0]
