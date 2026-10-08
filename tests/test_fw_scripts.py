"""/fwe router, scaffold, host-test runner, cross build, manifest and sim.

Each case builds its own workspace under tmp_path. The cross build runs on
the real motor-driver board and skips when the boards repo or the pinned
toolchain is absent; the sim case also skips without the pinned Renode.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fw_build  # noqa: E402
import fw_manifest  # noqa: E402
import fw_scaffold  # noqa: E402
import fw_sim  # noqa: E402
import fw_test  # noqa: E402
import fwe_setup  # noqa: E402
import task_router  # noqa: E402
from _boards import board_path, need_board  # noqa: E402
from test_pinmap import motor_fixture  # noqa: E402


BOARD = "bldc-motor-driver"


def run(mod, argv, tmp_path):
    out = tmp_path / "out.json"
    rc = mod.main([*argv, "--out", str(out)])
    return rc, json.loads(out.read_text())


def test_router_table_is_complete():
    assert task_router.validate() == []


@pytest.mark.parametrize("task,verb", [
    ("build it with warnings as errors", "build"),
    ("run the host unit tests", "test"),
    ("regenerate the pin map", "pinmap"),
    ("scaffold the firmware", "scaffold"),
    ("write sensored six-step", "stage"),
    ("install the toolchain", "setup"),
    ("run the renode smoke test", "sim"),
    ("write the manifest for npie", "manifest"),
])
def test_router_picks_one_verb(task, verb):
    assert task_router.match(task) == [verb]


def test_router_asks_for_a_board_and_rejects_nonsense(tmp_path):
    rc, res = run(task_router, ["--verb", "build"], tmp_path)
    assert (rc, res["status"]) == (1, "needs_args")
    rc, res = run(task_router, ["--task", "make coffee"], tmp_path)
    assert (rc, res["status"]) == (1, "unknown")
    rc, res = run(task_router, ["--verb", "setup"], tmp_path)
    assert rc == 0 and res["steps"][0]["cmd"].endswith("fwe_setup.py")


def test_scaffold_copies_missing_files_and_keeps_existing(tmp_path):
    ws = motor_fixture(tmp_path)
    mine = ws / "firmware" / "config" / "fw_config.h"
    mine.parent.mkdir(parents=True)
    mine.write_text("/* the board's own */\n")
    rc, res = run(fw_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    assert "config/fw_config.h" in res["kept"]
    assert mine.read_text() == "/* the board's own */\n"
    assert "CMakeLists.txt" in res["copied"]
    assert (ws / "firmware" / "gen" / "board_pins.h").is_file()
    rc, res = run(fw_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0 and res["copied"] == []


def _fw(tmp_path, test_src: str) -> Path:
    fw = tmp_path / "ws" / "firmware"
    (fw / "control").mkdir(parents=True)
    (fw / "tests").mkdir()
    (fw / "control" / "twice.c").write_text("int twice(int x) { return 2 * x; }\n")
    (fw / "tests" / "test_twice.c").write_text(
        "int twice(int x);\nint main(void) { return " + test_src + "; }\n")
    return fw.parent


@pytest.mark.parametrize("expr,status,rc", [
    ("twice(2) == 4 ? 0 : 1", "pass", 0),
    ("twice(2) == 5 ? 0 : 1", "fail", 1),
    ("undeclared_thing", "compile_error", 1),
])
def test_host_tests_pass_fail_and_compile_error(tmp_path, expr, status, rc):
    if not (shutil.which("cc") or shutil.which("gcc")):
        pytest.skip("no host C compiler")
    got_rc, res = run(fw_test, ["--workspace", str(_fw(tmp_path, expr))], tmp_path)
    assert got_rc == rc
    assert [t["status"] for t in res["tests"]] == [status]


def test_build_refuses_a_workspace_without_firmware(tmp_path):
    (tmp_path / "ws").mkdir()
    rc, res = run(fw_build, ["--workspace", str(tmp_path / "ws")], tmp_path)
    assert rc == 2 and "fw_scaffold" in res["error"]


def _toolchain_or_skip():
    env = fw_build.fwenv.tool_env()
    if not shutil.which("arm-none-eabi-gcc", path=env["PATH"]):
        pytest.skip("pinned arm toolchain not installed (fwe_setup.py)")


def test_motor_driver_scaffolds_builds_and_passes_host_tests(tmp_path):
    need_board(BOARD)
    _toolchain_or_skip()
    ws = tmp_path / board_path(BOARD).name
    shutil.copytree(board_path(BOARD) / "kicad", ws / "kicad")
    rc, res = run(fw_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    rc, res = run(fw_build, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res.get("log_tail") or res
    assert res["size"]["text"] < 128 * 1024
    assert set(res["artifacts"]) == {"elf", "bin", "hex"}
    rc, res = run(fw_test, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, [t for t in res["tests"] if t["status"] != "pass"]
    # a board re-spin the firmware has not seen fails the build at the pin map
    net = next((ws / "kicad").glob("*.net"))
    net.write_text(net.read_text().replace('LED_STATUS"', 'LED_STAT2"', 1))
    rc, res = run(fw_build, ["--workspace", str(ws)], tmp_path)
    assert (rc, res["step"]) == (1, "pinmap")


def test_manifest_and_sim_refuse_a_project_that_was_never_built(tmp_path):
    ws = motor_fixture(tmp_path)
    assert run(fw_scaffold, ["--workspace", str(ws)], tmp_path)[0] == 0
    rc, res = run(fw_manifest, ["--workspace", str(ws)], tmp_path)
    assert rc == 1 and "fw_build" in res["error"]
    assert not (ws / "firmware" / "fwe-manifest.json").exists()
    rc, res = run(fw_sim, ["--workspace", str(ws)], tmp_path)
    assert rc == 2 and not res["ok"]


def _built_motor(tmp_path) -> Path:
    need_board(BOARD)
    _toolchain_or_skip()
    ws = tmp_path / board_path(BOARD).name
    shutil.copytree(board_path(BOARD) / "kicad", ws / "kicad")
    assert run(fw_scaffold, ["--workspace", str(ws)], tmp_path)[0] == 0
    rc, res = run(fw_build, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res.get("log_tail") or res
    return ws


def test_motor_driver_manifest_is_derived_and_goes_stale(tmp_path):
    ws = _built_motor(tmp_path)
    rc, res = run(fw_manifest, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    m = res["manifest"]
    assert (m["board"], m["stage"], m["flash"]["connector"]) == ("PCB-0018-A", "bringup", "J601")
    # UART reaches J701 through the series resistors R701/R702
    assert (m["uart"]["connector"], m["uart"]["tx_pin"], m["uart"]["rx_pin"]) == ("J701", "3", "4")
    unsafe = {c["name"] for c in m["commands"] if not c["safe"]}
    assert unsafe == {"arm", "duty"}
    # /npie's asks: every console command listed, each with its reply's
    # top-level keys (nested o_obj keys are not), and the PWM frequency
    cmds = {c["name"]: c for c in m["commands"]}
    assert {"arm", "disarm", "duty", "clear", "status"} <= set(cmds)
    assert cmds["duty"]["reply_fields"] == ["duty", "max_duty"]
    assert "vbus" not in cmds["adc"]["reply_fields"] and "raw" in cmds["adc"]["reply_fields"]
    assert m["safety"]["pwm_hz"] == 20000
    assert m["safety"]["pwm_at_reset"] == "off" and m["safety"]["vbus_ov_v"] > m["safety"]["vbus_uv_v"]
    assert m["verified"] == {"build": True, "host_tests": True, "sim": None, "hardware": False}
    assert "trips" not in m and "pwm" not in m and "dead_time_ns" not in m["safety"]
    assert run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)[0] == 0
    # a stage's own command, declared on its dispatch line, reaches the
    # manifest with its args and safe flag, and --check accepts the rewrite
    con = ws / "firmware" / "src" / "console.c"
    src = con.read_text()
    line = '    else if (streq(c, "clear")) cmd_clear();'
    assert line in src
    con.write_text(src.replace(line, '    else if (streq(c, "hall")) cmd_clear();  /* fwe-cmd args="" safe=yes */\n' + line))
    assert run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)[0] == 1
    rc, res = run(fw_manifest, ["--workspace", str(ws)], tmp_path)
    assert rc == 0 and {c["name"]: c for c in res["manifest"]["commands"]}["hall"]["safe"] is True
    assert run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)[0] == 0
    cfg = ws / "firmware" / "config" / "fw_config.h"
    cfg.write_text(cfg.read_text().replace("VBUS_OV_V        30.0f", "VBUS_OV_V        32.0f"))
    rc, res = run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)
    assert (rc, res["stale"]) == (1, ["safety"])


def test_manifest_commands_take_a_stage_declaration_over_the_table(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "console.c").write_text(
        '    if (streq(c, "status")) cmd_status();\n'
        '    else if (streq(c, "six")) cmd_six(argc, argv);  '
        '/* fwe-cmd args="<duty 0..1> <fwd|rev> | stop" safe=no */\n'
        '    else if (streq(c, "hall")) cmd_hall();  /* fwe-cmd args="" safe=yes */\n'
        '    else if (streq(c, "led")) cmd_led(argc, argv);  /* fwe-cmd args="<x>" safe=no */\n')
    got = {c["name"]: (c["args"], c["safe"]) for c in fw_manifest.commands(tmp_path)}
    assert got == {
        "status": ("", True),                                 # table, undeclared
        "six": ("<duty 0..1> <fwd|rev> | stop", False),       # declared unsafe
        "hall": ("", True),                                   # declared read-only
        "led": ("<x>", False),                                # declaration beats the table
    }


def test_manifest_refuses_a_command_with_no_declared_args(tmp_path):
    # "fwe's manifest carries every command's arguments": a command in neither
    # the declaration nor the table is an error, never args "?"
    src = tmp_path / "src"
    src.mkdir()
    (src / "console.c").write_text(
        '    if (streq(c, "status")) cmd_status();\n'
        '    else if (streq(c, "spin")) cmd_spin(argc, argv);\n'
        '    else if (streq(c, "hall")) cmd_hall();  /* fwe-cmd args="" safe=yes */\n')
    with pytest.raises(fw_manifest.Undeclared, match=r"command\(s\) spin have no declared args"):
        fw_manifest.commands(tmp_path)


def test_motor_driver_boots_in_renode_and_answers(tmp_path):
    if not fw_sim.renode():
        pytest.skip("pinned Renode not installed (fwe_setup.py)")
    ws = _built_motor(tmp_path)
    rc, res = run(fw_sim, ["--workspace", str(ws), "--send", "version", "--send", "nonsense"], tmp_path)
    assert rc == 0, res
    assert res["banner"].startswith("fwe PCB-0018-A ") and res["boot_evt"]
    assert res["replies"][0]["reply"].startswith('OK {"board":"PCB-0018-A"')
    assert res["replies"][1]["reply"].startswith("ERR ")


def test_scaffold_picks_the_hrtim_boost_template_from_the_pin_roles(tmp_path):
    from test_pinmap import g474_workspace
    ws = g474_workspace(tmp_path)
    rc, res = run(fw_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    assert res["template"] == "stm32g474-boost"
    assert "src/hrtim.c" in res["copied"] and "src/pwm.c" not in res["copied"]


def test_scaffold_keeps_the_g431_template_without_hrtim_pins(tmp_path):
    ws = motor_fixture(tmp_path)
    rc, res = run(fw_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    assert res["template"] == "stm32g4"
    assert "src/pwm.c" in res["copied"] and "src/hrtim.c" not in res["copied"]


def test_g474_boost_builds_and_its_manifest_carries_the_pwm_and_the_trips(tmp_path):
    from test_pinmap import g474_workspace
    _toolchain_or_skip()
    ws = g474_workspace(tmp_path)
    assert run(fw_scaffold, ["--workspace", str(ws)], tmp_path)[0] == 0
    rc, res = run(fw_build, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res.get("log_tail") or res
    assert res["stage"] == "boost"          # the template's FWE_STAGE, not "bringup"
    rc, res = run(fw_manifest, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, res
    m = res["manifest"]
    assert (m["board"], m["stage"], m["mcu"]["part"]) == ("PCB-0026-A", "boost", "STM32G474CBT6")
    s = m["safety"]
    assert (s["pwm_hz"], s["dead_time_ns"], s["vout_ov_v"], s["i_trip_a"]) == (1000000, 10, 55.0, 17.0)
    assert s["vbus_uv_v"] < 12.0 < 24.0 < s["vbus_ov_v"]   # the input supply's limits
    assert [o["role"] for o in m["pwm"]["outputs"]] == ["hrtim_lo", "hrtim_hi"]
    trips = {t["name"]: t for t in m["trips"]}
    assert (trips["ovp"]["comparator"], trips["ovp"]["fault_input"], trips["ovp"]["threshold"]) == \
        ("COMP3", "FLT5", 55.0)
    assert (trips["ocp"]["comparator"], trips["ocp"]["fault_input"], trips["ocp"]["threshold"]) == \
        ("COMP1", "FLT4", 17.0)
    evt = 'EVT {"trip":{"new":["ovp_hw","ov"],"latched":["ovp_hw","ov"],"vout_v":55.2}}'
    assert re.match(trips["ovp"]["evt_regex"], evt) and not re.match(trips["ocp"]["evt_regex"], evt)
    assert {c["name"] for c in m["commands"] if not c["safe"]} == {"arm", "duty"}
    assert run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)[0] == 0
    cfg = ws / "firmware" / "config" / "fw_config.h"
    cfg.write_text(cfg.read_text().replace("VOUT_OV_V        55.0f", "VOUT_OV_V        56.0f"))
    rc, res = run(fw_manifest, ["--workspace", str(ws), "--check"], tmp_path)
    assert (rc, res["stale"]) == (1, ["safety", "trips"])


def _core_tree(tmp_path, monkeypatch, marker: str | None, paths: bool = True) -> dict:
    """A cmsis-core tree under a scratch FWE_TOOLS_DIR with this .fwe-commit."""
    monkeypatch.setenv("FWE_TOOLS_DIR", str(tmp_path / "tools"))
    e = next(x for x in fwe_setup.fwenv.lock()["sources"] if x["name"] == "cmsis-core")
    root = fwe_setup.fwenv.source_root(e)
    root.mkdir(parents=True)
    if paths:
        for p in e["paths"]:
            (root / p).mkdir(parents=True)
    if marker is not None:
        (root / ".fwe-commit").write_text(marker.replace("COMMIT", e["commit"]))
    return e


def _check_core(tmp_path) -> tuple[int, str]:
    rc, res = run(fwe_setup, ["--check", "--only", "cmsis-core"], tmp_path)
    return rc, res["items"][0]["status"]


def test_setup_check_passes_the_marker_setup_writes(tmp_path, monkeypatch):
    e = _core_tree(tmp_path, monkeypatch, None)
    (fwe_setup.fwenv.source_root(e) / ".fwe-commit").write_text(fwe_setup._marker(e))
    assert _check_core(tmp_path) == (0, "ok")


def test_setup_check_passes_a_commit_only_marker_with_the_paths_there(tmp_path, monkeypatch):
    _core_tree(tmp_path, monkeypatch, "COMMIT\n")      # written before #6 added the paths
    assert _check_core(tmp_path) == (0, "ok")


def test_setup_check_misses_a_commit_only_marker_without_the_paths(tmp_path, monkeypatch):
    _core_tree(tmp_path, monkeypatch, "COMMIT\n", paths=False)
    assert _check_core(tmp_path) == (1, "missing")


def test_setup_check_misses_another_commit(tmp_path, monkeypatch):
    _core_tree(tmp_path, monkeypatch, "0" * 40 + "\n")
    assert _check_core(tmp_path) == (1, "missing")


def test_setup_check_misses_a_marker_that_lacks_a_pinned_path(tmp_path, monkeypatch):
    _core_tree(tmp_path, monkeypatch, "COMMIT\nsome/other/path\n")
    assert _check_core(tmp_path) == (1, "missing")
