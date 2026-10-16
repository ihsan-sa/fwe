"""/fwe mcu_advice.py: fwe's advice to hwde on an MCU's setup, from a draft netlist.

Each case writes a small STM32G431 netlist (test_pinmap's fixture helpers)
and checks the advice on debug access, reset and the BOOT0 strap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import mcu_advice  # noqa: E402
from test_pinmap import _net, write_board  # noqa: E402

PA13, PA14 = ("U1", "37", "PA13_37"), ("U1", "38", "PA14_38")
NRST, BOOT0 = ("U1", "7", "PG10-NRST_7"), ("U1", "45", "PB8-BOOT0_45")
VDD = ("U1", "24", "VDD_24")


def board(tmp: Path, *, swdio="/SWDIO", boot=None, nrst_cap=True, comps=None, v33=()) -> Path:
    """A clean board unless told otherwise: SWD and NRST on J1, NRST's cap, BOOT0 pulled down by R1."""
    cs = {"U1": "STM32G431CBT6", "J1": "Conn_SWD", "R1": "10k", "C1": "100nF", **(comps or {})}
    nets = [
        _net(swdio, PA13, *([("J1", "2", "2")] if swdio == "/SWDIO" else [])),
        _net("/SWCLK", PA14, ("J1", "4", "4")),
        _net("/NRST", NRST, ("J1", "10", "10"), *([("C1", "1", "1")] if nrst_cap else [])),
        *(boot or [_net("/BOOT0", BOOT0, ("R1", "1", "1"))]),
        _net("+3V3", VDD, ("J1", "1", "1"), *v33),
        _net("GND", ("J1", "3", "3"), ("R1", "2", "2"), ("C1", "2", "2")),
    ]
    return write_board(tmp, nets, cs)


def topics(res, severity=None):
    return [(a["topic"], a["pin"]) for a in res["advice"] if severity in (None, a["severity"])]


def test_stm32_clean_board_has_no_advice(tmp_path):
    res = mcu_advice.advise(board(tmp_path), None)
    assert res["schema"] == "fwe-mcu-advice/1"
    assert res["mcu"] == {"ref": "U1", "part": "STM32G431CBT6", "table": "stm32g431"}
    assert res["advice"] == [] and res["ok"]


def test_stm32_swd_pin_used_for_something_else_is_a_must(tmp_path):
    res = mcu_advice.advise(board(tmp_path, swdio="/LED_RUN"), None)
    assert topics(res, "must") == [("debug", "PA13")]
    assert "LED_RUN" in res["advice"][0]["says"] and not res["ok"]


def test_stm32_swd_with_no_header_and_bare_nrst_are_shoulds(tmp_path):
    ws = write_board(tmp_path, [_net("/SWDIO", PA13), _net("/SWCLK", PA14, ("TP1", "1", "1")),
                                _net("/NRST", NRST), _net("/BOOT0", BOOT0, ("R1", "1", "1")),
                                _net("GND", ("R1", "2", "2"))],
                     {"U1": "STM32G431CBT6", "TP1": "TestPoint", "R1": "10k"})
    res = mcu_advice.advise(ws, None)
    assert topics(res) == [("debug", "PA13"), ("reset", "PG10"), ("reset", "PG10")]
    assert res["ok"]


def test_stm32_boot0_pulled_up_by_a_shared_i2c_pin_is_a_must(tmp_path):
    ws = board(tmp_path, boot=[_net("/I2C_SCL", BOOT0, ("R2", "1", "1"))], comps={"R2": "4k7"},
               v33=[("R2", "2", "2")])
    res = mcu_advice.advise(ws, None)
    assert topics(res, "must") == [("boot", "PB8")]
    assert "R2" in res["advice"][0]["says"]


def test_stm32_boot0_unconnected_or_divided_is_a_should(tmp_path):
    a = mcu_advice.advise(board(tmp_path / "a", boot=[_net("unconnected-(U1-PB8-BOOT0-Pad45)", BOOT0)]), None)
    assert topics(a) == [("boot", "PB8")] and a["ok"]
    div = [_net("/BOOT0", BOOT0, ("R1", "1", "1"), ("R2", "1", "1"))]
    b = mcu_advice.advise(board(tmp_path / "b", boot=div, comps={"R2": "10k"}, v33=[("R2", "2", "2")]), None)
    assert topics(b) == [("boot", "PB8")] and b["ok"]


def test_stm32_cli_writes_the_advice_and_exits_1_on_a_must(tmp_path, capsys):
    ws = board(tmp_path, swdio="/LED_RUN")
    assert mcu_advice.main(["--workspace", str(ws)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert json.loads((ws / "firmware" / "mcu-advice.json").read_text()) == out


def test_stm32_esp32_board_is_refused_for_now(tmp_path, capsys):
    ws = write_board(tmp_path, [_net("GND", ("U1", "1", "GND"))], {"U1": "ESP32-WROVER-E"})
    assert mcu_advice.main(["--workspace", str(ws)]) == 2
    assert "ESP32" in json.loads(capsys.readouterr().out)["error"]
