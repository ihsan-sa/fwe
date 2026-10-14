"""/fwe esp32 target: the router's split, and the ESP-IDF framework pin.

Each case stands on its own scratch FWE_TOOLS_DIR; nothing here installs IDF.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import fwe_setup  # noqa: E402
import task_router  # noqa: E402


def run(mod, argv, tmp_path):
    out = tmp_path / "out.json"
    rc = mod.main([*argv, "--out", str(out)])
    return rc, json.loads(out.read_text())


@pytest.mark.parametrize("task,verb", [
    ("install esp-idf", "esp32-setup"),
    ("set up the esp32 toolchain", "esp32-setup"),
    ("regenerate the squeezelite nvs config", "esp32-pinmap"),
    ("esp32 pin map for hifi-lite", "esp32-pinmap"),
    ("install the toolchain", "setup"),
    ("regenerate the pin map", "pinmap"),
])
def test_router_splits_esp32_from_mcu_tasks(task, verb):
    assert task_router.match(task) == [verb]


def test_router_plans_esp32_setup_for_idf_only(tmp_path):
    rc, res = run(task_router, ["--verb", "esp32-setup"], tmp_path)
    assert rc == 0 and res["steps"][0]["cmd"].endswith("fwe_setup.py --only esp-idf")


def test_lock_pins_idf_to_a_full_commit_and_upstream():
    idf = fwe_setup.fwenv.framework("esp-idf")
    assert len(idf["commit"]) == 40 and idf["tag"] == idf["version"]
    assert idf["targets"] == ["esp32"]
    up = {u["name"]: u for u in fwe_setup.fwenv.lock()["upstreams"]}
    assert len(up["squeezelite-esp32"]["commit"]) == 40


def _idf_tree(tmp_path, monkeypatch, marker: str | None) -> dict:
    monkeypatch.setenv("FWE_TOOLS_DIR", str(tmp_path / "tools"))
    e = fwe_setup.fwenv.framework("esp-idf")
    root = fwe_setup.fwenv.framework_root(e)
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "idf.py").write_text("")
    if marker is not None:
        (root / ".fwe-installed").write_text(marker)
    return e


def test_plain_setup_check_leaves_the_framework_out(tmp_path, monkeypatch):
    monkeypatch.setenv("FWE_TOOLS_DIR", str(tmp_path / "tools"))
    rc, res = run(fwe_setup, ["--check", "--only", "cmsis-core"], tmp_path)
    assert [i["name"] for i in res["items"]] == ["cmsis-core"]
    rc, res = run(fwe_setup, ["--check"], tmp_path)
    assert "esp-idf" not in [i["name"] for i in res["items"]]


def test_setup_check_passes_the_marker_install_writes(tmp_path, monkeypatch):
    e = _idf_tree(tmp_path, monkeypatch, None)
    (fwe_setup.fwenv.framework_root(e) / ".fwe-installed").write_text(fwe_setup._framework_marker(e))
    rc, res = run(fwe_setup, ["--check", "--only", "esp-idf"], tmp_path)
    assert (rc, res["items"][0]["status"]) == (0, "ok")


def test_setup_check_misses_a_half_install(tmp_path, monkeypatch):
    _idf_tree(tmp_path, monkeypatch, None)              # cloned, tools never finished
    rc, res = run(fwe_setup, ["--check", "--only", "esp-idf"], tmp_path)
    assert (rc, res["items"][0]["status"]) == (1, "missing")


def test_setup_check_misses_an_install_at_another_commit(tmp_path, monkeypatch):
    _idf_tree(tmp_path, monkeypatch, "0" * 40 + "\nesp32\n3.8\n")
    rc, res = run(fwe_setup, ["--check", "--frameworks"], tmp_path)
    idf = next(i for i in res["items"] if i["name"] == "esp-idf")
    assert (rc, idf["status"]) == (1, "missing")
