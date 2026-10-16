"""/fwe pinmap.py on an ESP32 board: squeezelite-esp32's NVS config from a netlist.

Each case writes its own small KiCad netlist (an ESP32-WROVER-E with a few
audio parts), so none needs the hifi boards.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import pinmap  # noqa: E402
from fwelib import squeezelite  # noqa: E402

U = "U1"  # the module; pin numbers are WROVER-E's, functions as KiCad names them


def _net(name, *nodes):
    body = " ".join(f'(node (ref "{r}") (pin "{p}") (pinfunction "{f}") (pintype "passive"))'
                    for r, p, f in nodes)
    return f'(net (code "1") (name "{name}") {body})'


def write_board(tmp: Path, nets: list[str], comps: dict[str, str]) -> Path:
    ws = tmp / "PCB-9998-A_esp"
    (ws / "kicad").mkdir(parents=True)
    cs = " ".join(f'(comp (ref "{r}") (value "{v}") (footprint "x"))' for r, v in comps.items())
    (ws / "kicad" / "PCB-9998-A_esp.net").write_text(
        f'(export (version "E") (components {cs}) (nets {" ".join(nets)}))\n')
    return ws


def base_nets() -> list[str]:
    return [
        _net("+3V3", (U, "2", "3V3")),
        _net("GND", (U, "1", "GND")),
        _net("/audio/I2S_BCK", (U, "16", "IO33"), ("U2", "13", "BCK")),
        _net("/audio/I2S_WS", (U, "11", "IO26"), ("U2", "15", "LRCK")),
        _net("/audio/I2S_DOUT", (U, "10", "IO25"), ("U2", "14", "DIN")),
        _net("/audio/XSMT_NET", (U, "14", "IO12"), ("U2", "17", "XSMT")),
        _net("/ui/IR_RX", (U, "12", "IO27")),
        _net("/ui/ENC_A", (U, "6", "IO34")),
        _net("/ui/ENC_B", (U, "7", "IO35")),
        _net("/ui/ENC_SW", (U, "5", "SENSOR_VN")),
        _net("unconnected-(U1-IO4)", (U, "26", "IO4")),
    ]


def test_gpio_names_from_module_pin_functions():
    assert squeezelite.gpio_of("IO25") == 25
    assert squeezelite.gpio_of("GPIO4") == 4
    assert squeezelite.gpio_of("IO25_10") == 25
    assert squeezelite.gpio_of("SENSOR_VP") == 36
    assert squeezelite.gpio_of("TXD0") == 1
    assert squeezelite.gpio_of("GND") is None
    assert squeezelite.gpio_of("EN") is None


def test_pcm5102_board_gives_dac_config_and_gpio_keys(tmp_path):
    ws = write_board(tmp_path, base_nets(), {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR"})
    m = pinmap.build(ws, None)
    assert m["findings"] == []
    cfg = m["squeezelite"]["config"]
    # XSMT is found through the part's pin, not its net name; high un-mutes, so mute is level 0.
    assert cfg["dac_config"] == "model=I2S,bck=33,ws=26,do=25,mute=12:0"
    assert "dac_controlset" not in cfg
    assert cfg["set_GPIO"] == "27=ir"
    assert cfg["rotary_config"] == "A=34,B=35,SW=39,volume,longpress"
    assert {p["pin"]: p["role"] for p in m["pins"]}["GPIO4"] == "unused"
    assert any("GPIO12" in n for n in m["notes"])        # a strapping pin is noted, not refused


def test_tpa3245_enable_and_fault_and_lan8720(tmp_path):
    nets = base_nets() + [
        _net("/amp/AMP_ON", (U, "24", "IO2"), ("U4", "9", "~{RESET}")),
        _net("/amp/AMP_FLT", (U, "8", "IO32"), ("U4", "10", "~{FAULT}")),
        _net("/amp/OTW", (U, "4", "SENSOR_VP"), ("U4", "11", "~{CLIP_OTW}")),
        _net("/eth/ETH_MDC", (U, "29", "IO23"), ("U5", "13", "MDC")),
        _net("/eth/ETH_MDIO", (U, "30", "IO18"), ("U5", "12", "MDIO")),
        _net("/eth/ETH_RST", (U, "27", "IO5"), ("U5", "15", "~{RST}")),
    ]
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR",
                                       "U4": "TPA3245DDW", "U5": "LAN8720A-CP"})
    m = pinmap.build(ws, None)
    cfg = m["squeezelite"]["config"]
    assert cfg["set_GPIO"] == "2=amp:1,27=ir,32=spkfault:0"
    assert cfg["eth_config"] == "model=lan8720,mdc=23,mdio=18,rst=5"
    assert m["squeezelite"]["fwe"]["amp_warn_gpio"] == "36:0"
    # LAN8720 fixes RMII on GPIO25/26/27, which this fixture gave to I2S and IR.
    taken = {f["pin"] for f in m["findings"] if f["kind"] == "rmii_pin_taken"}
    assert taken == {"GPIO25", "GPIO26", "GPIO27"}


def test_i2c_codec_gets_controlset_and_an_unverified_sequence_is_a_finding(tmp_path):
    nets = base_nets()[:5] + [
        _net("/audio/I2C_SDA", (U, "13", "IO14"), ("U2", "20", "SDA")),
        _net("/audio/I2C_SCL", (U, "23", "IO15"), ("U2", "21", "SCL")),
        _net("/audio/AMP_PDN", (U, "24", "IO2"), ("U2", "22", "PDN")),
    ]
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "TAS5825MRHBR"})
    m = pinmap.build(ws, None)
    cfg = m["squeezelite"]["config"]
    assert cfg["i2c_config"] == "scl=15,sda=14,speed=400000,port=0"
    assert cfg["dac_config"].startswith("model=I2S,bck=33,ws=26,do=25,sda=14,scl=15")
    ctl = json.loads(cfg["dac_controlset"])
    assert set(ctl) == {"init", "poweron", "poweroff"} and ctl["poweron"] == [{"reg": 3, "val": 3}]
    kinds = {f["kind"] for f in m["findings"]}
    assert {"codec_unverified", "i2c_addr_unknown"} <= kinds
    assert cfg["set_GPIO"] == "2=amp:1"


def test_hifi_max_tpa3255_amp_and_es9018k2m_dac(tmp_path):
    nets = [_net("+3V3", (U, "2", "3V3"), ("U2", "9", "ADDR")), _net("GND", (U, "1", "GND"))] + base_nets()[2:5] + [
        _net("/audio/I2C_SDA", (U, "13", "IO14"), ("U2", "20", "SDA")),
        _net("/audio/I2C_SCL", (U, "23", "IO15"), ("U2", "21", "SCL")),
        _net("/amp/AMP_ON", (U, "24", "IO2"), ("U4", "9", "~{RESET}")),
        _net("/amp/AMP_FLT", (U, "8", "IO32"), ("U4", "10", "~{FAULT}")),
        _net("/amp/OTW", (U, "4", "SENSOR_VP"), ("U4", "11", "~{CLIP_OTW}")),
    ]
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "ES9018K2M", "U4": "TPA3255DDV"})
    m = pinmap.build(ws, None)
    assert {(p["ref"], p["kind"]) for p in m["parts"]} == {("U2", "dac"), ("U4", "amp")}
    cfg = m["squeezelite"]["config"]
    # The analog amp is not an I2S sink, so the DAC owns dac_config; ADDR high is 0x49.
    assert cfg["dac_config"].split(",")[:4] == ["model=I2S", "bck=33", "ws=26", "do=25"]
    assert "i2c=73" in cfg["dac_config"].split(",")
    assert cfg["set_GPIO"] == "2=amp:1,32=spkfault:0"
    assert m["squeezelite"]["fwe"]["amp_warn_gpio"] == "36:0"
    kinds = {f["kind"] for f in m["findings"]}
    assert {"codec_unverified", "codec_pins_unchecked"} <= kinds and "several_i2s_sinks" not in kinds
    # The TPA3255's pins are taken from the TPA3245 and not checked, so the amp gets its own finding.
    assert {f["ref"] for f in m["findings"] if f["kind"] == "codec_pins_unchecked"} == {"U2", "U4"}


def test_hifi_lite_tas5825p_is_not_taken_for_the_tas5825m(tmp_path):
    nets = base_nets()[:5] + [
        _net("/audio/I2C_SDA", (U, "13", "IO14"), ("U2", "20", "SDA")),
        _net("/audio/I2C_SCL", (U, "23", "IO15"), ("U2", "21", "SCL")),
        _net("/audio/AMP_PDN", (U, "24", "IO2"), ("U2", "22", "PDN")),
    ]
    m = pinmap.build(write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "TAS5825PRHBR"}), None)
    cfg = m["squeezelite"]["config"]
    # The TAS5825M's unchecked sequence would be a wrong guess for the P; its init stays empty.
    assert json.loads(cfg["dac_controlset"]) == {"init": [], "poweron": [], "poweroff": []}
    assert cfg["set_GPIO"] == "2=amp:1"
    assert {"codec_unverified", "codec_pins_unchecked"} <= {f["kind"] for f in m["findings"]}


def _isns_board(tmp: Path, func: str) -> dict:
    """The amp rail: an INA180A2 (no REF pin) across a 5 mOhm shunt, its OUT through R10 to `func`."""
    nets = base_nets()[:5] + [
        _net("/amp/PVDD_IN", ("R11", "1", ""), ("U5", "4", "IN+")),
        _net("/amp/PVDD", ("R11", "2", ""), ("U5", "5", "IN-")),
        _net("/amp/ISNS_OUT", ("U5", "1", "OUT"), ("R10", "1", "")),
        _net("/amp/AMP_ISNS", (U, "6", func), ("R10", "2", "")),
        _net("GND", (U, "1", "GND"), ("U5", "2", "GND")),
    ]
    tmp.mkdir()
    comps = {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102A", "U5": "INA180A2", "R10": "100", "R11": "5mR"}
    return pinmap.build(write_board(tmp, nets, comps), None)


def test_amp_rail_current_sense_gets_its_adc1_channel_and_scaling(tmp_path):
    m = _isns_board(tmp_path / "adc1", "IO34")
    a = m["analog"]["AMP_ISNS"]
    assert (a["amp"], a["gain_v_per_v"], a["shunt_ohm"], a["ref_v"], a["adc1_channel"]) == \
        ("U5", 50, 0.005, 0.0, 6)
    h = squeezelite.header(m)
    assert "#define RAIL_ISNS_ADC1_CH 6" in h and "#define RAIL_ISNS_V_PER_A 0.25f" in h
    assert "#define RAIL_ISNS_REF_V 0.0f" in h
    # On an ADC2 pin it can't be read with Wi-Fi up: a finding, and no scaling for the limiter.
    m = _isns_board(tmp_path / "adc2", "IO4")
    assert m["analog"] == {} and "isns_not_adc1" in {f["kind"] for f in m["findings"]}


def test_ak4493s_address_reads_both_straps_and_smute_mutes_high(tmp_path):
    # i2c_addr is indexed by CAD1 CAD0; the old code read CAD0 alone, so CAD1 high gave 16 or 17.
    for cad1, cad0, want in ((0, 0, 16), (0, 1, 17), (1, 0, 18), (1, 1, 19)):
        straps = {"+3V3": [(U, "2", "3V3")], "GND": [(U, "1", "GND")]}
        straps["+3V3" if cad1 else "GND"].append(("U2", "22", "CAD1"))
        straps["+3V3" if cad0 else "GND"].append(("U2", "23", "CAD0"))
        nets = [_net(rail, *nodes) for rail, nodes in straps.items()] + base_nets()[2:5] + [
            _net("/audio/I2C_SDA", (U, "13", "IO14"), ("U2", "20", "SDA")),
            _net("/audio/I2C_SCL", (U, "23", "IO15"), ("U2", "21", "SCL")),
            _net("/audio/DAC_SOFTMUTE", (U, "14", "IO12"), ("U2", "6", "SMUTE")),
        ]
        ws = write_board(tmp_path / str(want), nets, {U: "ESP32-WROVER-E-N8R8", "U2": "AK4493SEQ"})
        m = pinmap.build(ws, None)
        kinds = {f["kind"] for f in m["findings"]}
        assert "i2c_addr_unknown" not in kinds, want
        # The address map and SMUTE level are not from the datasheet, so they stay a finding.
        assert "codec_pins_unchecked" in kinds
        f = m["squeezelite"]["config"]["dac_config"].split(",")
        assert f"i2c={want}" in f and "mute=12:1" in f, (want, f)


def _strap_board(tmp: Path, value: str, high: list, low: list) -> dict:
    nets = [_net("+3V3", (U, "2", "3V3"), *high), _net("GND", (U, "1", "GND"), *low)] + base_nets()[2:5] + [
        _net("/audio/I2C_SDA", (U, "13", "IO14"), ("U2", "20", "SDA")),
        _net("/audio/I2C_SCL", (U, "23", "IO15"), ("U2", "21", "SCL")),
    ]
    return pinmap.build(write_board(tmp, nets, {U: "ESP32-WROVER-E-N8R8", "U2": value}), None)


def test_a_single_adr_or_addr_strap_picks_one_of_two_addresses(tmp_path):
    # ES9038Q2M has two addresses; ADR (one D) and ADDR are both one strap pin.
    for name in ("ADR", "ADDR"):
        for high, want in ((False, 72), (True, 73)):
            pin = [("U2", "9", name)]
            m = _strap_board(tmp_path / f"{name}{want}", "ES9038Q2M", pin if high else [], [] if high else pin)
            assert "i2c_addr_unknown" not in {f["kind"] for f in m["findings"]}, (name, want)
            assert f"i2c={want}" in m["squeezelite"]["config"]["dac_config"].split(","), (name, want)


def test_a_strap_shared_with_another_function_still_counts(tmp_path):
    # KiCad names a dual-use pin 'CAD0/CSN'; it is still the CAD0 strap.
    m = _strap_board(tmp_path, "AK4493SEQ", [("U2", "23", "CAD0/CSN")], [("U2", "22", "CAD1")])
    assert "i2c=17" in m["squeezelite"]["config"]["dac_config"].split(",")


def test_a_bare_ad_pin_is_not_a_strap(tmp_path):
    m = _strap_board(tmp_path, "ES9038Q2M", [("U2", "9", "AD")], [])
    assert "i2c_addr_unknown" in {f["kind"] for f in m["findings"]}


def test_output_on_input_only_pin_and_reserved_pin_are_findings(tmp_path):
    nets = base_nets() + [_net("/LED_RED", (U, "6b", "IO36")), _net("/BTN_PLAY", (U, "9", "IO16"))]
    nets[7] = _net("/LED_GREEN", (U, "6", "IO34"))
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR"})
    m = pinmap.build(ws, None)
    bad = {(f["kind"], f["pin"]) for f in m["findings"]}
    assert ("input_only_pin", "GPIO34") in bad and ("input_only_pin", "GPIO36") in bad
    assert ("reserved_pin", "GPIO16") in bad
    assert m["squeezelite"]["fwe"]["buttons"] == "play=16"


def test_line_in_adc_goes_to_our_namespace(tmp_path):
    nets = base_nets() + [_net("/audio/I2S_DIN", (U, "8", "IO32"), ("U6", "8", "DOUT"))]
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR", "U6": "PCM1808PWR"})
    m = pinmap.build(ws, None)
    assert m["findings"] == []
    assert m["squeezelite"]["fwe"]["linein_config"] == "model=PCM1808,bck=33,ws=26,di=32"
    assert "linein_config" not in m["squeezelite"]["config"]


def test_pcm1863_wired_mux_inputs_are_tone_taps(tmp_path):
    nets = base_nets() + [
        _net("/audio/I2S_DIN", (U, "8", "IO32"), ("U6", "8", "DOUT")),
        _net("/audio/DAC_OUTL", ("U2", "6", "OUTL"), ("C5", "1", "")),
        _net("Net-(C5-Pad2)", ("C5", "2", ""), ("U6", "1", "VINL1")),          # through its coupling cap
        _net("/audio/AMP_SENSE_R", ("U6", "2", "VINR1")),
        _net("unconnected-(U6-VINL2)", ("U6", "3", "VINL2")),
    ]
    ws = write_board(tmp_path, nets, {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR", "U6": "PCM1863PWR",
                                       "C5": "1u"})
    m = pinmap.build(ws, None)
    assert m["tone_taps"] == [{"tap": "VINL1", "ref": "U6", "net": "DAC_OUTL"},
                              {"tap": "VINR1", "ref": "U6", "net": "AMP_SENSE_R"}]
    # The input pin names are from memory, so the ADC carries a codec_pins_unchecked finding.
    assert {f["ref"] for f in m["findings"] if f["kind"] == "codec_pins_unchecked"} == {"U6"}
    pm = write_board(tmp_path / "b", base_nets(), {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR"})
    assert pinmap.build(pm, None)["tone_taps"] == []


def test_nvs_csv_round_trips_through_csv_and_refuses_long_keys():
    text = squeezelite.nvs_csv({"config": {"dac_config": "model=I2S,bck=33",
                                           "dac_controlset": '{"init":[]}'}, "fwe": {}})
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["key", "type", "encoding", "value"]
    assert rows[1] == ["config", "namespace", "", ""]
    assert rows[2] == ["dac_config", "data", "string", "model=I2S,bck=33"]
    assert rows[3][3] == '{"init":[]}'
    assert len(rows) == 4                                  # an empty namespace is left out
    try:
        squeezelite.nvs_csv({"config": {"a_key_far_too_long": "x"}})
    except ValueError:
        pass
    else:
        raise AssertionError("a 16-character key must be refused")


def test_later_series_are_told_apart_from_the_classic_esp32():
    for part in ("ESP32-WROVER-E-N8R8", "ESP32-WROOM-32E", "ESP32-PICO-D4", "ESP32-SOLO-1", "ESP32-D0WD-V3"):
        assert squeezelite.later_series(part) is None, part
    assert squeezelite.later_series("ESP32-S3-WROOM-1-N16R8") == "ESP32-S3"
    assert squeezelite.later_series("ESP32-C3-MINI-1") == "ESP32-C3"
    assert squeezelite.later_series("esp32c6-wroom-1") == "ESP32-C6"


def test_a_c3_or_s3_board_is_refused_not_given_classic_pins(tmp_path, capsys):
    for part in ("ESP32-S3-WROOM-1-N16R8", "ESP32-C3-MINI-1"):
        ws = write_board(tmp_path / part, base_nets(), {U: part, "U2": "PCM5102APWR"})
        assert pinmap.main(["--workspace", str(ws)]) == 2
        assert part[:8] in json.loads(capsys.readouterr().out)["error"]
        assert not (ws / "firmware").exists()


def test_main_writes_csv_and_check_catches_a_respin(tmp_path, capsys):
    ws = write_board(tmp_path, base_nets(), {U: "ESP32-WROVER-E-N8R8", "U2": "PCM5102APWR"})
    assert pinmap.main(["--workspace", str(ws)]) == 0
    capsys.readouterr()
    fw = ws / "firmware"
    assert "dac_config" in (fw / "gen" / "nvs_config.csv").read_text()
    assert "#define PIN_I2S_BCK_GPIO 33" in (fw / "gen" / "board_pins.h").read_text()
    assert pinmap.main(["--workspace", str(ws), "--check"]) == 0
    capsys.readouterr()
    net = ws / "kicad" / "PCB-9998-A_esp.net"
    net.write_text(net.read_text().replace('"IO27"', '"IO13"'))
    assert pinmap.main(["--workspace", str(ws), "--check"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert "firmware/gen/nvs_config.csv" in res["drift"]
