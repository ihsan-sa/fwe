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


# ESP32-WROVER-E pin numbers, functions as KiCad names them (as test_esp32_pinmap does).
EN, IO0, IO2, IO12, IO15 = ("U1", "3", "EN"), ("U1", "25", "IO0"), ("U1", "24", "IO2"), \
    ("U1", "14", "IO12"), ("U1", "23", "IO15")
TXD0, RXD0 = ("U1", "35", "TXD0"), ("U1", "34", "RXD0")


def esp_board(tmp: Path, *, en_cap=True, en=True, tx="/UART_TX", extra=(), comps=None, v33=(), gnd=()) -> Path:
    """A clean board unless told otherwise: EN 10k up and 1 uF down, GPIO0 10k up with a BOOT button, UART0 on J1."""
    cs = {"U1": "ESP32-WROVER-E-N8R8", "J1": "Conn_UART", "R1": "10k", "R2": "10k", "C1": "1uF",
          "SW1": "SW_Push", **(comps or {})}
    nets = [
        _net("+3V3", ("U1", "2", "3V3"), ("R1", "1", "1"), ("R2", "1", "1"), ("J1", "1", "1"), *v33),
        _net("GND", ("U1", "1", "GND"), ("SW1", "2", "2"), ("J1", "3", "3"),
             *([("C1", "2", "2")] if en_cap else []), *gnd),
        _net("/EN", *([EN] if en else []), ("R1", "2", "2"), *([("C1", "1", "1")] if en_cap else [])),
        _net("/BOOT", IO0, ("R2", "2", "2"), ("SW1", "1", "1")),
        _net(tx, TXD0, *([("J1", "4", "4")] if tx == "/UART_TX" else [])),
        _net("/UART_RX", RXD0, ("J1", "5", "5")),
        *extra,
    ]
    return write_board(tmp, nets, cs)


def test_esp32_clean_board_has_no_advice(tmp_path):
    res = mcu_advice.advise(esp_board(tmp_path), None)
    assert res["mcu"] == {"ref": "U1", "part": "ESP32-WROVER-E-N8R8", "table": "esp32"}
    assert res["advice"] == [] and res["ok"]


def test_esp32_mtdi_pulled_up_by_a_part_is_a_must(tmp_path):
    ws = esp_board(tmp_path, extra=[_net("/I2C_SDA", IO12, ("R3", "1", "1"))], comps={"R3": "4k7"},
                   v33=[("R3", "2", "2")])
    res = mcu_advice.advise(ws, None)
    assert topics(res, "must") == [("boot", "GPIO12")] and not res["ok"]
    assert "R3" in res["advice"][0]["says"] and "1.8 V" in res["advice"][0]["why"]


def test_esp32_gpio2_high_is_a_must_and_mtdo_low_a_should(tmp_path):
    ws = esp_board(tmp_path, extra=[_net("/LED_STATUS", IO2, ("R3", "1", "1")),
                                    _net("/DAC_MUTE", IO15, ("R4", "1", "1"))],
                   comps={"R3": "10k", "R4": "10k"}, v33=[("R3", "2", "2")], gnd=[("R4", "2", "2")])
    res = mcu_advice.advise(ws, None)
    assert topics(res, "must") == [("boot", "GPIO2")]
    assert topics(res, "should") == [("boot", "GPIO15")]


def test_esp32_gpio0_with_no_button_and_en_without_its_cap_are_shoulds(tmp_path):
    ws = write_board(tmp_path, [
        _net("+3V3", ("U1", "2", "3V3"), ("R1", "1", "1"), ("J1", "1", "1")),
        _net("/EN", EN, ("R1", "2", "2")),
        _net("unconnected-(U1-IO0-Pad25)", IO0),
        _net("/UART_TX", TXD0, ("R5", "1", "1")), _net("/TX_J", ("R5", "2", "2"), ("J1", "4", "4")),
        _net("/UART_RX", RXD0, ("U3", "5", "TXD"))],
        {"U1": "ESP32-WROVER-E", "J1": "Conn_UART", "R1": "10k", "R5": "470", "U3": "CP2102N"})
    res = mcu_advice.advise(ws, None)
    assert topics(res) == [("boot", "GPIO0"), ("reset", "EN")] and res["ok"]   # UART0 reaches J1 and U3


def test_esp32_en_floating_or_uart0_taken_is_a_must(tmp_path):
    ws = esp_board(tmp_path, en=False, tx="/I2S_MCLK", extra=[_net("unconnected-(U1-EN-Pad3)", EN)])
    res = mcu_advice.advise(ws, None)
    assert topics(res, "must") == [("reset", "EN"), ("uart", "GPIO1")]
    assert "I2S_MCLK" in res["advice"][-1]["says"]


def test_esp32_s3_is_refused(tmp_path, capsys):
    ws = write_board(tmp_path, [_net("GND", ("U1", "1", "GND"))], {"U1": "ESP32-S3-WROOM-1"})
    assert mcu_advice.main(["--workspace", str(ws)]) == 2
    assert "ESP32-S3" in json.loads(capsys.readouterr().out)["error"]
