"""/fwe FPGA target: router, scaffold, manifest, synthesis and the cocotb bench.

Each case scaffolds its own workspace under tmp_path. The bench and the
synthesis need chip-flow's bin/eda (CHIP_FLOW_HOME) and skip with the reason
when it is absent: never a silent pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import fpga_build  # noqa: E402
import fpga_manifest  # noqa: E402
import fpga_scaffold  # noqa: E402
import fpga_setup  # noqa: E402
import fpga_sim  # noqa: E402
import task_router  # noqa: E402
from fwelib import gateware  # noqa: E402


def run(mod, argv, tmp_path):
    out = tmp_path / "out.json"
    rc = mod.main([*argv, "--out", str(out)])
    return rc, json.loads(out.read_text())


def need_eda():
    if not gateware.eda().is_file():
        pytest.skip(f"needs chip-flow's bin/eda at {gateware.eda()} (CHIP_FLOW_HOME)")


def need_pnr():
    need_eda()
    if not gateware.tool("nextpnr-ecp5") or not gateware.tool("ecppack"):
        pytest.skip("needs nextpnr-ecp5 and ecppack: fpga_setup.py --install")


def scaffolded(tmp_path, **geometry) -> Path:
    ws = tmp_path / "PCB-0025-A_pwm-fpga-8ch"
    ws.mkdir()
    assert fpga_scaffold.main(["--workspace", str(ws), "--out", str(tmp_path / "s.json")]) == 0
    if geometry:
        p = ws / "firmware" / "gateware.json"
        cfg = json.loads(p.read_text())
        cfg.update(geometry)
        p.write_text(json.dumps(cfg))
    return ws


@pytest.mark.parametrize("task,verb", [
    ("build the gateware", "fpga-build"),
    ("synthesise the rtl", "fpga-build"),
    ("run the fpga testbench", "fpga-sim"),
    ("simulate the fpga pwm", "fpga-sim"),
    ("install the fpga toolchain", "fpga-setup"),
    ("scaffold the gateware", "fpga-scaffold"),
    ("write the fpga manifest for npie", "fpga-manifest"),
    ("review the gateware", "fpga-review"),
    # the MCU verbs keep their tasks
    ("build it with warnings as errors", "build"),
    ("install the toolchain", "setup"),
    ("run the renode smoke test", "sim"),
])
def test_router_splits_fpga_from_mcu_tasks(task, verb):
    assert task_router.match(task) == [verb]


def test_scaffold_keeps_the_handoff_readme_and_reports_the_missing_board(tmp_path):
    ws = tmp_path / "board"
    readme = ws / "firmware" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("handoff\n")
    rc, res = run(fpga_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0 and "rtl/pwm8_core.v" in res["copied"] and "gateware.json" in res["copied"]
    assert readme.read_text() == "handoff\n"
    assert "pwm_pins" in res["board_missing"] and "part" in res["board_missing"]
    rc, res = run(fpga_scaffold, ["--workspace", str(ws)], tmp_path)
    assert rc == 0 and res["copied"] == [] and "README.md" not in res["kept"]


def test_geometry_says_what_a_step_is_and_refuses_a_bad_split():
    geo = gateware.geometry({"f_rf_hz": 13_560_000, "channels": 8, "steps_per_period": 72,
                             "word_bits": 8, "uart_baud": 115200})
    assert geo["problems"] == [] and abs(geo["step_s"] - 1.0243e-9) < 1e-12
    assert geo["fabric_clk_hz"] == 122_040_000 and geo["phase_bits"] == 7
    bad = gateware.geometry({"f_rf_hz": 13_560_000, "channels": 8, "steps_per_period": 74,
                             "word_bits": 8, "uart_baud": 115200})
    assert bad["problems"] and "multiple" in bad["problems"][0]


def test_manifest_carries_the_protocol_and_goes_stale(tmp_path):
    ws = scaffolded(tmp_path)
    rc, res = run(fpga_manifest, ["--workspace", str(ws), "--check"], tmp_path)
    assert rc == 1 and res["stale"]                     # none on disk yet
    rc, res = run(fpga_manifest, ["--workspace", str(ws)], tmp_path)
    assert rc == 0
    man = json.loads((ws / "firmware" / "fwe-manifest.json").read_text())
    assert (man["schema"], man["board"], man["kind"]) == ("fwe-fpga-manifest/1", "PCB-0025-A", "fpga")
    regs = {r["name"]: r for r in man["registers"]}
    assert regs["phase7"]["addr"] == 0x17 and regs["phase7"]["range"] == [0, 71]
    assert regs["duty0"]["range"] == [0, 72] and len(man["outputs"]) == 8
    # nothing ran on this design, so nothing is claimed
    assert man["verified"] == {"sim": False, "synth": False, "bitstream": False, "hardware": False}
    assert man["artifact"]["bitstream"] is None
    rc, _ = run(fpga_manifest, ["--workspace", str(ws), "--check"], tmp_path)
    assert rc == 0
    cfg = json.loads((ws / "firmware" / "gateware.json").read_text())
    cfg["board"]["part"] = "LFE5U-25F-6BG256C"
    (ws / "firmware" / "gateware.json").write_text(json.dumps(cfg))
    rc, res = run(fpga_manifest, ["--workspace", str(ws), "--check"], tmp_path)
    assert rc == 1 and "fpga" in res["stale"]


def test_a_recorded_result_counts_only_for_the_design_it_ran_on(tmp_path):
    ws = scaffolded(tmp_path)
    fw = ws / "firmware"
    gateware.record(fw, "sim", {"ok": True})
    assert gateware.recorded_ok(fw, "sim")
    gateware.record(fw, "build", {"ok": False})
    assert not gateware.recorded_ok(fw, "build")
    core = fw / "rtl" / "pwm8_core.v"
    core.write_text(core.read_text() + "\n")
    assert not gateware.recorded_ok(fw, "sim")


def test_synth_maps_the_core_and_the_bitstream_waits_for_the_board(tmp_path):
    need_eda()
    ws = scaffolded(tmp_path, steps_per_period=56, word_bits=4)
    rc, res = run(fpga_build, ["--workspace", str(ws), "--synth-only"], tmp_path)
    assert rc == 0, res
    assert res["family"] == "ecp5" and res["cells"].get("TRELLIS_FF", 0) > 0
    rc, res = run(fpga_build, ["--workspace", str(ws)], tmp_path)
    assert rc == 2 and res["step"] == "bitstream" and "not chosen" in res["error"]


def test_bench_proves_phase_step_and_skew_at_both_geometries(tmp_path):
    need_eda()
    for n, w in ((72, 8), (56, 4)):
        sub = tmp_path / f"n{n}"
        sub.mkdir()
        ws = scaffolded(sub, steps_per_period=n, word_bits=w)
        rc, res = run(fpga_sim, ["--workspace", str(ws)], sub)
        assert rc == 0, res
        assert {"test_phase_moves_the_edge_one_step_per_count",
                "test_eight_channels_hold_zero_skew_and_set_skew",
                "test_commit_applies_all_channels_in_the_same_period"} <= set(res["tests"])
        assert res["failed"] == [] and res["geometry"]["steps_per_period"] == n


def test_bench_fails_when_the_phase_is_off_by_one(tmp_path):
    need_eda()
    ws = scaffolded(tmp_path)
    core = ws / "firmware" / "rtl" / "pwm8_core.v"
    src = core.read_text()
    good = "start[i] <= (ph_t[i] == 0) ? 0 : N - ph_t[i];"
    assert good in src
    core.write_text(src.replace(good, "start[i] <= (ph_t[i] == 0) ? 0 : N - 1 - ph_t[i];"))
    rc, res = run(fpga_sim, ["--workspace", str(ws)], tmp_path)
    assert rc == 1 and "test_phase_moves_the_edge_one_step_per_count" in res["failed"]


EVN = "lfe5um5g-85f-evn"


def test_scaffold_fills_a_known_board_and_keeps_one_already_filled(tmp_path):
    ws = tmp_path / "PCB-0025-A_pwm-fpga-8ch"
    ws.mkdir()
    rc, res = run(fpga_scaffold, ["--workspace", str(ws), "--board", EVN], tmp_path)
    assert rc == 0 and res["board"] == EVN and res["board_missing"] == []
    cfg = gateware.load(ws / "firmware")
    assert (cfg["steps_per_period"], cfg["word_bits"]) == (56, 4)
    assert cfg["board"]["pwm_pins"][0] == "M18" and cfg["board"]["ref_clk_pin"] == "A10"
    assert cfg["calibration"]["coarse"] == [0] * 8      # the template's, untouched
    cfg["board"]["pwm_pins"][0] = "A1"
    (ws / "firmware" / "gateware.json").write_text(json.dumps(cfg))
    rc, res = run(fpga_scaffold, ["--workspace", str(ws), "--board", EVN], tmp_path)
    assert rc == 0 and res["board"] is None
    assert gateware.load(ws / "firmware")["board"]["pwm_pins"][0] == "A1"
    rc, res = run(fpga_scaffold, ["--workspace", str(ws), "--board", "no-such-board"], tmp_path)
    assert rc == 2 and EVN in res["error"]


def test_clocking_gives_the_evn_plls_and_refuses_a_vco_out_of_range():
    prof = json.loads((ROOT / "skill" / "templates" / "fpga-boards" / f"{EVN}.json").read_text())
    cfg = {"f_rf_hz": 13_560_000, "channels": 8, "uart_baud": 115200, **prof["geometry"],
           "board": prof["board"]}
    clk = gateware.clocking(cfg)
    assert clk["problems"] == [] and clk["eclk_hz"] == 379_687_500
    assert abs(clk["step_s"] - 1.3169e-9) < 1e-13 and abs(clk["f_rf_ppm"] - 19.75) < 0.01
    assert clk["sclk_hz"] == 189_843_750 and clk["uart_cpb"] == 1648
    cfg["board"] = {**prof["board"], "pll": [{**prof["board"]["pll"][0], "CLKOP_DIV": 70},
                                             prof["board"]["pll"][1]]}
    assert any("PLL1 VCO" in p for p in gateware.clocking(cfg)["problems"])
    assert gateware.clocking({**cfg, "board": {}}) is None


def test_manifest_carries_the_trim_registers_and_the_calibration_load(tmp_path):
    ws = scaffolded(tmp_path, steps_per_period=56, word_bits=4,
                    calibration={"source": "bench 2026-10-01", "coarse": [0, 2, 1, 0, 0, 2, 1, 0],
                                 "fine": [0, 7, 40, 99, 12, 0, 3, 127]})
    assert run(fpga_manifest, ["--workspace", str(ws)], tmp_path)[0] == 0
    man = json.loads((ws / "firmware" / "fwe-manifest.json").read_text())
    regs = {r["name"]: r for r in man["registers"]}
    assert regs["trim_coarse0"]["addr"] == 0x20 and regs["trim_coarse0"]["range"] == [0, 55]
    assert regs["trim_fine7"]["addr"] == 0x2F and regs["trim_fine7"]["range"] == [0, 127]
    assert regs["fine_taps"]["value"] == 128 and "3" in regs["ctrl"]["bits"]
    cal = man["calibration"]
    assert cal["source"] == "bench 2026-10-01" and cal["problems"] == []
    assert cal["table"][3] == {"channel": 3, "coarse": 0, "fine": 99}
    assert {"addr": 0x21, "value": 2} in cal["load"] and {"addr": 0x2F, "value": 127} in cal["load"]
    assert len(cal["load"]) == 16
    # a value the register would refuse is named, not loaded silently
    p = ws / "firmware" / "gateware.json"
    cfg = json.loads(p.read_text())
    cfg["calibration"]["fine"][1] = 128
    cfg["calibration"]["coarse"][2] = 56
    p.write_text(json.dumps(cfg))
    assert run(fpga_manifest, ["--workspace", str(ws)], tmp_path)[0] == 0
    probs = json.loads((ws / "firmware" / "fwe-manifest.json").read_text())["calibration"]["problems"]
    assert probs == ["ch2 coarse 56 outside 0..55", "ch1 fine 128 outside 0..127"]


def _suite(tmp_path, names) -> Path:
    import tarfile
    src = tmp_path / "src" / "oss-cad-suite" / "bin"
    src.mkdir(parents=True)
    for n in names:
        (src / n).write_text("#!/bin/sh\necho 1\n")
        (src / n).chmod(0o755)
    tgz = tmp_path / "home" / ".cache" / "fwe" / "dl" / fpga_setup.ASSET
    tgz.parent.mkdir(parents=True)
    with tarfile.open(tgz, "w:gz") as t:
        t.add(src.parent, arcname="oss-cad-suite")
    return tgz


def test_install_unpacks_the_pinned_suite_in_user_space(tmp_path, monkeypatch):
    import hashlib
    tgz = _suite(tmp_path, fpga_setup.PNR)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("FWE_FPGA_TOOLS", str(tmp_path / "home" / "tools" / "oss-cad-suite"))
    monkeypatch.setattr(fpga_setup, "URL", "http://127.0.0.1:9/never-fetched")
    monkeypatch.setattr(fpga_setup, "SHA256", hashlib.sha256(tgz.read_bytes()).hexdigest())
    assert fpga_setup.install() is None
    for n in fpga_setup.PNR:
        assert (tmp_path / "home" / "tools" / "oss-cad-suite" / "bin" / n).is_file()
    assert gateware.tool("ecppack") in ([str(gateware.tools_home() / "bin" / "ecppack")],
                                        [str(gateware.eda()), "ecppack"])
    assert fpga_setup.install() is None               # already there: kept, nothing fetched


def test_install_refuses_a_download_that_is_not_the_pinned_one(tmp_path, monkeypatch):
    tgz = _suite(tmp_path, fpga_setup.PNR)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("FWE_FPGA_TOOLS", str(tmp_path / "home" / "tools" / "oss-cad-suite"))
    monkeypatch.setattr(fpga_setup, "SHA256", "0" * 64)
    err = fpga_setup.install()
    assert err and "not the pinned" in err and not tgz.exists()
    assert not (tmp_path / "home" / "tools").exists()


def test_bench_fails_when_the_delay_line_walks_the_wrong_way(tmp_path):
    need_eda()
    ws = scaffolded(tmp_path)
    taps = ws / "firmware" / "rtl" / "pwm8_taps.v"
    src = taps.read_text()
    good = "direction[k] <= (tgt[k] < cur[k]);"
    assert good in src
    taps.write_text(src.replace(good, "direction[k] <= (tgt[k] > cur[k]);"))
    rc, res = run(fpga_sim, ["--workspace", str(ws)], tmp_path)
    assert rc == 1 and "test_fine_trim_walks_each_delay_line_to_its_tap" in res["failed"]
    assert "test_phase_moves_the_edge_one_step_per_count" not in res["failed"]


def test_evn_bitstream_meets_timing_with_a_delay_on_every_pin(tmp_path):
    need_pnr()
    ws = tmp_path / "PCB-0025-A_pwm-fpga-8ch"
    ws.mkdir()
    assert run(fpga_scaffold, ["--workspace", str(ws), "--board", EVN], tmp_path)[0] == 0
    rc, res = run(fpga_build, ["--workspace", str(ws)], tmp_path)
    assert rc == 0, {k: res.get(k) for k in ("step", "error", "timing", "log_tail")}
    assert res["step"] == "bitstream" and (ws / "firmware" / "build" / "pwm8.bit").stat().st_size > 0
    assert res["output_delays"] == 8
    assert all(v["achieved_mhz"] >= v["constraint_mhz"] for v in res["timing"].values())
    lpf = (ws / "firmware" / "build" / "pnr" / "pwm8.lpf").read_text()
    assert 'LOCATE COMP "pwm[7]" SITE "U18";' in lpf and "DRIVE=8 SLEWRATE=FAST" in lpf
    assert run(fpga_manifest, ["--workspace", str(ws)], tmp_path)[0] == 0
    man = json.loads((ws / "firmware" / "fwe-manifest.json").read_text())
    assert man["verified"]["bitstream"] and man["artifact"]["sha256"]
