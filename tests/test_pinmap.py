"""/fwe pinmap.py: firmware pins and analog scaling derived from a netlist.

Each case writes its own small KiCad netlist; one case runs on the real
motor-driver board and skips when the boards repo is absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import pinmap  # noqa: E402
from _boards import board_path, need_board  # noqa: E402

MCU_PINS = {  # LQFP48 number -> pinfunction, the few pins the fixtures use
    "30": "PA8_30", "31": "PA9_31", "32": "PA10_32", "27": "PB13_27",
    "28": "PB14_28", "29": "PB15_29", "9": "PA1_9", "8": "PA0_8",
    "43": "PB6_43", "44": "PB7_44", "13": "PA5_13", "24": "VDD_24",
}


def _net(name, *nodes):
    body = " ".join(f'(node (ref "{r}") (pin "{p}") (pinfunction "{f}") (pintype "passive"))'
                    for r, p, f in nodes)
    return f'(net (code "1") (name "{name}") {body})'


def write_board(tmp: Path, nets: list[str], comps: dict[str, str]) -> Path:
    ws = tmp / "PCB-9999-A_fixture"
    (ws / "kicad").mkdir(parents=True)
    cs = " ".join(f'(comp (ref "{r}") (value "{v}") (footprint "x"))' for r, v in comps.items())
    (ws / "kicad" / "PCB-9999-A_fixture.net").write_text(
        f'(export (version "E") (components {cs}) (nets {" ".join(nets)}))\n')
    return ws


def u(pin):
    return ("U1", pin, MCU_PINS[pin])


def motor_fixture(tmp: Path, *, inlc_pin="29", extra=()) -> Path:
    comps = {"U1": "STM32G431CBT6", "U2": "INA240A1", "R1": "3mR 2512", "NT1": "NetTie_2",
             "NT2": "NetTie_2", "R2": "100 ohm", "R3": "150k", "R4": "10k", "C1": "10uF"}
    nets = [
        _net("/INHA", u("30")), _net("/INHB", u("31")), _net("/INHC", u("32")),
        _net("/INLA", u("27")), _net("/INLB", u("28")), _net("/INLC", u(inlc_pin)),
        _net("/UART_TX", u("43")), _net("/UART_RX", u("44")),
        _net("/ISENSE_A", u("9"), ("R2", "2", "2")),
        _net("/sensing/CSA_A_OUT", ("R2", "1", "1"), ("U2", "5", "OUT_5")),
        _net("+3V3", u("24"), ("U2", "7", "REF1_7"), ("U2", "6", "VS_6")),
        _net("GND", ("U2", "3", "REF2_3"), ("R1", "2", "2"), ("NT2", "1", "1"),
             ("R4", "2", "2"), ("C1", "2", "2")),
        _net("/LS_SRC_A", ("R1", "1", "1"), ("NT1", "1", "1")),
        _net("/ISNS_A_P", ("NT1", "2", "2"), ("U2", "8", "IN+_8")),
        _net("/ISNS_A_N", ("NT2", "2", "2"), ("U2", "1", "IN-_1")),
        _net("VM", ("R3", "1", "1"), ("C1", "1", "1")),
        _net("/VBUS_SENSE", u("8"), ("R3", "2", "2"), ("R4", "1", "1")),
        *extra,
    ]
    return write_board(tmp, nets, comps)


def by_net(m):
    return {p["net"]: p for p in m["pins"] if p["net"]}


def test_ohms_parses_the_value_styles_boards_use():
    assert pinmap.ohms("150k") == 150e3
    assert pinmap.ohms("3mR 2512 3W 1%") == pytest.approx(0.003)
    assert pinmap.ohms("100 ohm") == 100
    assert pinmap.ohms("4k7") == 4700
    assert pinmap.ohms("3.3R DNP") == 3.3
    assert pinmap.ohms("LED red") is None


def test_fixture_pins_functions_and_scaling(tmp_path):
    m = pinmap.build(motor_fixture(tmp_path), None)
    pins = by_net(m)
    assert m["findings"] == []
    assert pins["INHA"]["function"] == {"name": "TIM1_CH1", "af": 6, "peripheral": "TIM1"}
    assert pins["INLA"]["function"]["name"] == "TIM1_CH1N"
    assert pins["INLC"]["function"]["name"] == "TIM1_CH3N"
    assert pins["UART_TX"]["function"]["name"] == "USART1_TX"
    assert pins["ISENSE_A"]["function"]["adc"] in (1, 2)
    isa = m["analog"]["ISENSE_A"]
    assert (isa["gain_v_per_v"], isa["shunt_ohm"], isa["ref_v"]) == (20, 0.003, 1.65)
    assert isa["volts_per_amp"] == pytest.approx(0.06)
    vb = m["analog"]["VBUS_SENSE"]
    assert (vb["source"], vb["ratio"]) == ("VM", 16.0)
    assert m["rails"]["+3V3"] == 3.3


def test_unknown_net_is_a_finding_and_known_ones_are_not(tmp_path):
    ws = motor_fixture(tmp_path, extra=[_net("/MYSTERY", u("13"))])
    m = pinmap.build(ws, None)
    assert [f for f in m["findings"] if f["kind"] == "unclassified"] == [
        {"kind": "unclassified", "pin": "PA5", "net": "MYSTERY"}]
    assert by_net(m)["INHA"]["role"] == "gate_hi"


def test_gate_pins_without_a_common_timer_channel_are_a_finding(tmp_path):
    # INLC on PA5 (no TIM1_CH3N there): the pwm group has no common timer
    m = pinmap.build(motor_fixture(tmp_path, inlc_pin="13"), None)
    kinds = {f["kind"] for f in m["findings"]}
    assert "no_common_peripheral" in kinds
    assert "function" not in by_net(m)["INHA"]


def test_check_passes_on_a_fresh_map_and_fails_after_a_respin(tmp_path, capsys):
    ws = motor_fixture(tmp_path)
    assert pinmap.main(["--workspace", str(ws)]) == 0
    assert (ws / "firmware" / "gen" / "board_pins.h").is_file()
    capsys.readouterr()
    assert pinmap.main(["--workspace", str(ws), "--check"]) == 0
    assert json.loads(capsys.readouterr().out)["drift"] == []
    net = ws / "kicad" / "PCB-9999-A_fixture.net"
    net.write_text(net.read_text().replace('"/UART_TX"', '"/UART_TXD"'))
    assert pinmap.main(["--workspace", str(ws), "--check"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert "firmware/gen/board_pins.h" in out["drift"]


BOARD = "PCB-0018-A_bldc-motor-driver"


def test_motor_driver_board():
    need_board(BOARD)
    m = pinmap.build(board_path(BOARD), None)
    assert m["findings"] == []
    assert m["mcu"]["part"] == "STM32G431CBT6"
    pins = by_net(m)
    for net, name in (("INHA", "TIM1_CH1"), ("INHC", "TIM1_CH3"), ("INLA", "TIM1_CH1N"),
                      ("INLC", "TIM1_CH3N"), ("UART_TX", "USART1_TX"),
                      ("UART_RX", "USART1_RX"), ("HALL_A", "TIM2_CH1"),
                      ("HALL_C", "TIM2_CH3")):
        assert pins[net]["function"]["name"] == name, net
    for phase in "ABC":
        a = m["analog"][f"ISENSE_{phase}"]
        assert (a["amp_part"], a["gain_v_per_v"], a["shunt_ohm"], a["ref_v"]) == \
            ("INA240A1", 20, 0.003, 1.65)
        assert m["analog"][f"VSENSE_{phase}"]["ratio"] == 16.0
    assert m["analog"]["VBUS_SENSE"]["source"] == "VM"
    assert {pins[n]["role"] for n in ("LED_STATUS", "LED_FAULT")} == {"led"}


def test_c_float_literals_are_valid_c():
    assert pinmap._f(16) == "16.0f"
    assert pinmap._f(0.003) == "0.003f"
    assert pinmap._f(1.65) == "1.65f"
    assert pinmap._f(1e-9) == "1e-09f"


def test_generated_header_compiles(tmp_path):
    import shutil
    import subprocess
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")  # the order fw_test.py uses
    if not cc:
        pytest.skip("no host C compiler")
    ws = motor_fixture(tmp_path)
    assert pinmap.main(["--workspace", str(ws), "--out", str(tmp_path / "r.json")]) == 0
    src = tmp_path / "use.c"
    src.write_text('#include "board_pins.h"\n'
                   "float k(void) { return VBUS_SENSE_RATIO * ISENSE_A_GAIN * ISENSE_A_SHUNT_OHM"
                   " + ISENSE_A_REF_V + RAIL__3V3_V; }\n")
    p = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-c", str(src),
                        "-I", str(ws / "firmware" / "gen"), "-o", str(tmp_path / "use.o")],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


GOLD = ROOT / "tests" / "golden" / "pinmap"
G474_WS = "PCB-0026-A_gan-boost-48v"


def g474_workspace(tmp: Path) -> Path:
    """A scratch workspace holding the golden copy of PCB-0026-A's netlist."""
    ws = tmp / G474_WS
    (ws / "kicad").mkdir(parents=True)
    (ws / "kicad" / f"{G474_WS}.net").write_bytes((GOLD / f"{G474_WS}.net").read_bytes())
    return ws


def test_golden_g474_boost_pinmap(tmp_path, capsys):
    ws = g474_workspace(tmp_path)
    assert pinmap.main(["--workspace", str(ws)]) == 0
    capsys.readouterr()
    fw = ws / "firmware"
    assert (fw / "pinmap.json").read_text() == (GOLD / "PCB-0026-A.pinmap.json").read_text()
    assert (fw / "gen" / "board_pins.h").read_text() == \
        (GOLD / "PCB-0026-A.board_pins.h").read_text()
    m = json.loads((fw / "pinmap.json").read_text())
    assert m["mcu"]["part"] == "STM32G474CBT6" and m["mcu"]["table"] == "stm32g474"
    pins = by_net(m)
    assert pins["PWM_LO"]["function"] == {"name": "HRTIM1_CHA1", "af": 13,
                                          "peripheral": "HRTIM1_TIMA", "output": 1}
    assert pins["PWM_HI"]["function"]["name"] == "HRTIM1_CHA2"
    assert m["analog"]["VOUT_SNS"]["ratio"] == 21.0      # 100k + 100k over 10k, past a 100R filter
    assert m["analog"]["ISNS"]["volts_per_amp"] == pytest.approx(0.05)
    assert m["analog"]["NTC_SNS"]["beta"] == 3380
    assert [(r["trip"], r["comp"], r["fault"]) for r in m["fault_routes"]] == \
        [("ovp", "COMP3", "FLT5"), ("ocp", "COMP1", "FLT4")]  # RM0440 Rev 9 Table 228
    assert m["findings"] == []


_load_mcu_table = pinmap.load_mcu_table


def _g474_table(status: str) -> tuple[str, dict]:
    fam, table = _load_mcu_table("STM32G474CBT6")
    table = json.loads(json.dumps(table))
    # FLT7/FLT8 do not exist on the G4: fixture values, not the RM0440 mapping.
    table["hrtim"]["fault_internal_sources"].update(
        status=status, verified_against="fixture", map={"FLT7": "COMP1", "FLT8": "COMP3"})
    return fam, table


def test_fault_route_is_named_only_from_a_verified_table(tmp_path, monkeypatch):
    ws = g474_workspace(tmp_path)
    monkeypatch.setattr(pinmap, "load_mcu_table", lambda part: _g474_table("verified"))
    m = pinmap.build(ws, None)
    assert [(r["trip"], r["fault"]) for r in m["fault_routes"]] == [("ovp", "FLT8"), ("ocp", "FLT7")]
    assert m["findings"] == []
    assert "#define TRIP_OCP_FLT 7u" in pinmap.header(m)


def test_fault_route_from_an_unverified_table_is_a_finding(tmp_path, monkeypatch):
    ws = g474_workspace(tmp_path)
    monkeypatch.setattr(pinmap, "load_mcu_table", lambda part: _g474_table("unverified"))
    m = pinmap.build(ws, None)
    assert [r["fault"] for r in m["fault_routes"]] == [None, None]
    assert [f["comp"] for f in m["findings"] if f["kind"] == "fault_route_unverified"] == \
        ["COMP3", "COMP1"]
    assert "TRIP_OCP_FLT" not in pinmap.header(m)


def test_a_board_without_hrtim_has_no_fault_routes(tmp_path):
    m = pinmap.build(motor_fixture(tmp_path), None)
    assert "fault_routes" not in m
