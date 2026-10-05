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
    good = "d = (t >= ph_a[k]) ? t - ph_a[k] : t + N - ph_a[k];"
    assert good in src
    core.write_text(src.replace(good, "d = (t > ph_a[k]) ? t - ph_a[k] : t + N - ph_a[k];"))
    rc, res = run(fpga_sim, ["--workspace", str(ws)], tmp_path)
    assert rc == 1 and "test_phase_moves_the_edge_one_step_per_count" in res["failed"]
