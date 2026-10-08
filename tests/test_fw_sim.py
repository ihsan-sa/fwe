"""fw_sim.py without Renode: which repl and console UART it picks, the .resc
it writes for the HRTIM scenario, and how it reads the HRTIM result from a
canned Renode log and console transcript."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import fw_sim  # noqa: E402

TPL = ROOT / "skill" / "templates"
G431 = TPL / "stm32g4" / "sim" / "g431.repl"
G474 = TPL / "stm32g474-boost" / "sim" / "g474.repl"


def _ws(tmp_path: Path, repls: list[Path]) -> Path:
    ws = tmp_path / "PCB-0026-A_gan-boost-48v"
    fw = ws / "firmware"
    (fw / "sim").mkdir(parents=True)
    (fw / "build").mkdir()
    (fw / "build" / "fw.elf").write_bytes(b"\x7fELF")
    for r in repls:
        (fw / "sim" / r.name).write_text(r.read_text())
    return ws


def test_zero_repls_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(fw_sim, "renode", lambda: Path("/bin/true"))
    rc, res = fw_sim.run(_ws(tmp_path, []), ["version"], 1, 1)
    assert rc == 2 and "no *.repl" in res["error"]


def test_several_repls_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(fw_sim, "renode", lambda: Path("/bin/true"))
    rc, res = fw_sim.run(_ws(tmp_path, [G431, G474]), ["version"], 1, 1)
    assert rc == 2 and "several *.repl" in res["error"]
    assert "g431.repl" in res["error"] and "g474.repl" in res["error"]


def test_console_uart_and_hrtim_come_from_the_repl(tmp_path):
    repl, err = fw_sim.find_repl(_ws(tmp_path, [G474]) / "firmware" / "sim")
    assert err is None and repl.name == "g474.repl"
    assert fw_sim.console_uart(G474.read_text()) == "usart2"
    assert fw_sim.console_uart(G431.read_text()) == "usart1"
    assert fw_sim.has_hrtim(G474.read_text()) and not fw_sim.has_hrtim(G431.read_text())
    assert fw_sim.console_uart("flash: Memory.MappedMemory @ sysbus 0x0\n") is None


def test_script_runs_the_hrtim_scenario_only_with_the_stub(tmp_path):
    elf = tmp_path / "fw.elf"
    g431 = fw_sim.script(tmp_path, "g431.repl", "usart1", elf, ["version"], 4)
    assert "usart1 WriteChar 0x76" in g431 and "HR " not in g431 and "0x400173F0" not in g431
    g474 = fw_sim.script(tmp_path, "g474.repl", "usart2", elf, ["version"], 4, inject=5)
    assert "usart2 CreateFileBackend" in g474 and "usart1" not in g474
    assert "sysbus ReadDoubleWord 0x40016894" in g474          # Timer A PER
    assert "sysbus WriteDoubleWord 0x400173F0 5" in g474        # FLT5 inject
    assert g474.index('echo "HR TRIP"') < g474.rindex('echo "HR OENR"')


def test_fw_defines_reads_the_template_config():
    d = fw_sim.fw_defines(TPL / "stm32g474-boost")
    assert d["PWM_FREQ_HZ"] == 1_000_000 and d["DEADTIME_NS"] == 10
    assert d["HRTIM_FHRTIM_HZ"] == 170_000_000 and d["TRIP_OVP_FLT"] == 5   # default: no gen/


LOG = """\x1b[32mStarting emulation...\x1b[0m
HR PER
0x00001540
HR CMP1
0x00000000
HR DT
0x000E000E
HR OENR
0x00000003
HR TRIP
HR OENR
0x00000000
HR ISR
0x00010010
"""
UART = ['fwe PCB-0026-A 0.1.0 boost',
        'EVT {"trip":{"new":["ovp_hw"],"latched":["ovp_hw"]}}']
STATUS = 'OK {"state":"off","outputs_on":false,"trips":["ovp_hw"],"active":[]}'


def test_hrtim_result_from_a_canned_log():
    vals = fw_sim.parse_monitor(LOG)
    assert vals == {"PER": 0x1540, "CMP1": 0, "DT": 0x000E000E, "OENR": 3,
                    "OENR_after": 0, "ISR_after": 0x10010}
    hr = fw_sim.hrtim_result(vals, UART, fw_sim.DEFAULTS, "OK {}", STATUS)
    assert hr["fsw_hz"] == 1_000_000.0                          # 5.44 GHz / 5440
    assert hr["dead_time_ns"] == {"rise": 10.294, "fall": 10.294, "step": 0.735}
    assert hr["outputs_before"] == 3 and hr["outputs_after_trip"] == 0
    assert hr["trip_evt"].startswith('EVT {"trip"')
    assert all(hr["checks"].values())


def test_hrtim_checks_fail_honestly():
    vals = fw_sim.parse_monitor(LOG.replace("0x00001540", "0x00001600")
                                .replace("0x000E000E", "0x0014000E")
                                .replace("HR TRIP\nHR OENR\n0x00000000", "HR TRIP\nHR OENR\n0x00000002"))
    hr = fw_sim.hrtim_result(vals, UART, fw_sim.DEFAULTS, None,
                             STATUS.replace('["ovp_hw"]', "[]"))
    assert hr["checks"] == {"fsw": False, "dead_time": False,
                            "outputs_off_after_trip": False, "trip_latched": False}
    none = fw_sim.hrtim_result({}, [], fw_sim.DEFAULTS, None, None)
    assert not any(none["checks"].values()) and none["fsw_hz"] is None and none["trip_evt"] is None
