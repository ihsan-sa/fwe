"""/fwe's ESP32 scaffold, host tests and build checks, offline.

Each case makes its own board (test_esp32_pinmap's fixture netlist) and its
own small git repo standing in for upstream squeezelite-esp32, so none needs
the network, ESP-IDF or the hifi boards.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import esp32_build  # noqa: E402
import esp32_manifest  # noqa: E402
import esp32_test  # noqa: E402
import fw_scaffold  # noqa: E402
from fwelib import upstream  # noqa: E402
from test_esp32_pinmap import base_nets, write_board  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def fake_upstream(tmp: Path) -> tuple[Path, list[str]]:
    """A repo shaped like upstream (components/, build-scripts/) with two commits."""
    repo = tmp / "upstream-src"
    (repo / "components" / "squeezelite").mkdir(parents=True)
    (repo / "build-scripts").mkdir()
    (repo / "components" / "squeezelite" / "CMakeLists.txt").write_text("# upstream\n")
    (repo / "build-scripts" / "I2S-4MFlash-sdkconfig.defaults").write_text("CONFIG_X=y\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("two\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "two")
    return repo, [first, git(repo, "rev-parse", "HEAD")]


@pytest.fixture
def board(tmp_path, monkeypatch):
    repo, commits = fake_upstream(tmp_path)
    pin = {"name": upstream.NAME, "repo": str(repo), "commit": commits[0]}
    monkeypatch.setattr(upstream, "entry", lambda: pin)
    ws = write_board(tmp_path, base_nets(), {"U1": "ESP32-WROVER-E-N8R8", "U2": "PCM5102A"})
    return ws, pin, commits


def test_scaffold_clones_pinned_commit_and_links_components(board):
    ws, pin, _ = board
    rc, res = fw_scaffold.scaffold(ws)
    assert rc == 0, res
    fw = ws / "firmware"
    up = fw / "upstream"
    assert res["template"] == "esp32"
    assert res["upstream"]["commit"] == pin["commit"]   # the pin, not the repo's tip
    assert res["linked"] == ["fwe_board", "fwe_pd_limit", "fwe_selftest", "fwe_stub", "fwe_webapp", "fwe_xover"]
    assert (up / "components" / "fwe_stub").resolve() == (fw / "components" / "fwe_stub").resolve()
    assert (up / "components" / "fwe_stub" / "core" / "fwe_stub.c").is_file()
    assert git(up, "status", "--porcelain") == ""        # the links never show in upstream
    assert (fw / "gen" / "nvs_config.csv").is_file()
    assert "upstream/" in (fw / ".gitignore").read_text()
    assert git(up, "remote") == "origin"                # no remote of ours added


def test_scaffold_reports_a_clone_at_another_commit_and_update_moves_it(board):
    ws, pin, commits = board
    assert fw_scaffold.scaffold(ws)[0] == 0
    pin["commit"] = commits[1]                          # the lock moves on
    rc, res = fw_scaffold.scaffold(ws)
    assert rc == 1 and res["upstream"]["finding"] == "upstream_moved"
    assert upstream.head(ws / "firmware" / "upstream") == commits[0]
    rc, res = fw_scaffold.scaffold(ws, update=True)
    assert rc == 0, res
    assert upstream.head(ws / "firmware" / "upstream") == commits[1]


def test_scaffold_keeps_a_file_the_board_already_has(board):
    ws, _, _ = board
    fw_scaffold.scaffold(ws, fetch=False)
    stub = ws / "firmware" / "components" / "fwe_stub" / "core" / "fwe_stub.c"
    stub.write_text("/* ours now */\n")
    rc, res = fw_scaffold.scaffold(ws, fetch=False)
    assert "components/fwe_stub/core/fwe_stub.c" in res["kept"]
    assert stub.read_text() == "/* ours now */\n"
    assert "upstream" not in res and not (ws / "firmware" / "upstream").exists()


def test_host_tests_pass_on_the_template(board):
    ws, _, _ = board
    fw_scaffold.scaffold(ws, fetch=False)
    rc, res = esp32_test.run(ws / "firmware")
    assert rc == 0, [t["output"] for t in res["tests"] if not t["ok"]]
    assert [t["name"] for t in res["tests"]] == ["test_fwe_pd_limit", "test_fwe_selftest", "test_fwe_stub", "test_fwe_webapp", "test_fwe_xover"]


def test_host_tests_fail_on_a_wrong_result_and_on_a_warning(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    core = fw / "components" / "fwe_stub" / "core" / "fwe_stub.c"
    core.write_text(core.read_text().replace("return lo;", "return hi;"))
    rc, res = esp32_test.run(fw)
    by_name = {t["name"]: t for t in res["tests"]}
    assert rc == 1 and not by_name["test_fwe_stub"]["ok"] and by_name["test_fwe_pd_limit"]["ok"]
    assert by_name["test_fwe_xover"]["ok"] and by_name["test_fwe_webapp"]["ok"]
    core.write_text(core.read_text().replace("return hi;", "return lo;")
                    + "static int unused_fn(void) { return 0; }\n")
    rc, res = esp32_test.run(fw)
    assert rc == 1 and all(t["output"].startswith("build:") for t in res["tests"])


def test_werror_check_flags_an_fwe_source_built_without_it(tmp_path):
    cc = [
        {"file": "/w/firmware/upstream/components/fwe_stub/core/fwe_stub.c",
         "command": "xtensa-esp32-elf-gcc -Wall -Werror -c fwe_stub.c"},
        {"file": "/w/firmware/upstream/components/fwe_x/x.c",
         "command": "xtensa-esp32-elf-gcc -Wall -c x.c"},
        {"file": "/w/firmware/upstream/components/squeezelite/a.c",
         "command": "xtensa-esp32-elf-gcc -c a.c"},
    ]
    (tmp_path / "compile_commands.json").write_text(json.dumps(cc))
    ok, bad = esp32_build.werror_sources(tmp_path)
    assert ok == [cc[0]["file"]]
    assert bad == [cc[1]["file"]]                       # upstream's own sources are not judged


def test_platform_comes_from_sdkconfig_fwe(tmp_path):
    assert esp32_build.platform(tmp_path, None) == esp32_build.DEFAULT_PLATFORM
    (tmp_path / "sdkconfig.fwe").write_text("# PLATFORM=SqueezeAmp\nCONFIG_X=y\n")
    assert esp32_build.platform(tmp_path, None) == "SqueezeAmp"
    assert esp32_build.platform(tmp_path, "Muse") == "Muse"


def test_a_changed_platform_or_sdkconfig_fwe_drops_the_old_sdkconfig(tmp_path):
    fw, b = tmp_path, tmp_path / "build"
    b.mkdir()
    sdk = b / "sdkconfig"

    def built(key):                                     # as main() keeps it after a build
        sdk.write_text("CONFIG_X=y\n")
        (b / "fwe_build.json").write_text(json.dumps({"sdkconfig": {**key, "regenerated": False}}))

    key = esp32_build.sdkconfig_key(fw, "I2S-4MFlash")
    assert key["sdkconfig_fwe_sha256"] is None
    assert not esp32_build.drop_stale_sdkconfig(b, key)  # nothing to drop yet
    built(key)
    assert not esp32_build.drop_stale_sdkconfig(b, key) and sdk.is_file()
    assert esp32_build.drop_stale_sdkconfig(b, esp32_build.sdkconfig_key(fw, "Muse"))
    assert not sdk.exists()
    built(key)
    (fw / "sdkconfig.fwe").write_text("CONFIG_Y=y\n")
    assert esp32_build.drop_stale_sdkconfig(b, esp32_build.sdkconfig_key(fw, "I2S-4MFlash"))
    sdk.write_text("CONFIG_X=y\n")
    (b / "fwe_build.json").write_text("{}")             # a build from before the key was kept
    assert esp32_build.drop_stale_sdkconfig(b, key)


def test_build_refuses_an_upstream_off_the_pin(board):
    ws, pin, commits = board
    fw_scaffold.scaffold(ws)
    pin["commit"] = commits[1]
    rc, res = esp32_build.build(ws, None)
    assert rc == 1 and res["step"] == "upstream"


def test_build_without_a_scaffolded_upstream_is_an_error(board):
    ws, _, _ = board
    fw_scaffold.scaffold(ws, fetch=False)
    rc, res = esp32_build.build(ws, None)
    assert rc == 2 and res["step"] == "upstream"


def test_flash_args_split_options_from_offsets():
    text = ("--flash_mode dio --flash_freq 80m --flash_size 4MB\n0x1000 bootloader/bootloader.bin\n"
            "0x10000 squeezelite.bin\n0x8000 partition_table/partition-table.bin\n")
    opts, flash = esp32_build.flash_args(text)
    assert opts == ["--flash_mode", "dio", "--flash_freq", "80m", "--flash_size", "4MB"]
    assert flash == [["0x1000", "bootloader/bootloader.bin"], ["0x10000", "squeezelite.bin"],
                     ["0x8000", "partition_table/partition-table.bin"]]
    assert esp32_build.flash_args("") == ([], [])


def scaffolded_with_idf(board, tmp_path, monkeypatch):
    """A scaffolded board at the pin, with ESP-IDF taken as installed and idf() replaced."""
    ws, _, _ = board
    assert fw_scaffold.scaffold(ws)[0] == 0
    monkeypatch.setenv("FWE_TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.setattr(esp32_build, "_framework_ok", lambda e: (True, "test"))
    return ws


def test_build_without_esp_idf_says_how_to_install_it(board, tmp_path, monkeypatch):
    ws, _, _ = board
    assert fw_scaffold.scaffold(ws)[0] == 0
    monkeypatch.setenv("FWE_TOOLS_DIR", str(tmp_path / "no-tools"))
    rc, res = esp32_build.build(ws, None)
    assert rc == 2 and res["step"] == "idf"
    assert "missing" in res["error"] and "fwe_setup.py --only esp-idf" in res["error"]


def test_a_build_that_times_out_is_a_failed_build_step(board, tmp_path, monkeypatch):
    ws = scaffolded_with_idf(board, tmp_path, monkeypatch)

    def slow(env, *args, cwd, timeout=5400):
        raise subprocess.TimeoutExpired(args, timeout, output=b"[12/900] Building C object\n")

    monkeypatch.setattr(esp32_build, "idf", slow)
    rc, res = esp32_build.build(ws, None)
    assert rc == 1 and res["step"] == "build" and "timed out after 5400s" in res["error"]
    log = (ws / "firmware" / "build" / "fwe_build.log").read_text()
    assert log.startswith("[12/900] Building C object") and "timed out" in log


def fake_build(fw: Path, ok: bool = True) -> None:
    """Images and a fwe_build.json as esp32_build.py leaves them."""
    b = fw / "build"
    (b / "bootloader").mkdir(parents=True)
    (b / "bootloader" / "bootloader.bin").write_bytes(b"boot")
    (b / "nvs_config.bin").write_bytes(b"nvs")
    flash = [["0x1000", "bootloader/bootloader.bin"], ["0x3c0000", "nvs_config.bin"]]
    arts = {f: {"path": str(b / f), "sha256": esp32_build.sha256(b / f)} for _, f in flash}
    (b / "fwe_build.json").write_text(json.dumps(
        {"ok": ok, "platform": "I2S-4MFlash", "upstream": {"commit": "abc"},
         "flash": flash, "artifacts": arts,
         "flash_options": ["--flash_mode", "dio", "--flash_freq", "80m", "--flash_size", "4MB"],
         "nvs_csv_sha256": esp32_build.sha256(fw / "gen" / "nvs_config.csv")}))


def test_manifest_lists_images_in_flash_order_with_nvs_last(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    fake_build(fw)
    esp32_test.main(["--workspace", str(ws), "--out", str(fw / "t.json")])
    man, err = esp32_manifest.derive(fw)
    assert err is None
    assert man["schema"] == "fwe-esp32-manifest/1"
    assert man["mcu"]["flash_mb"] == 8 and man["mcu"]["psram_mb"] == 8
    assert [i["name"] for i in man["images"]] == ["bootloader", "nvs_config"]
    assert man["flash"]["command"][7:9] == ["--flash_mode", "dio"]
    assert man["flash"]["command"][-4:] == ["0x1000", "build/bootloader/bootloader.bin",
                                           "0x3c0000", "build/nvs_config.bin"]
    assert man["nvs"]["namespaces"]["config"]["set_GPIO"] == "27=ir"
    assert man["verified"] == {"build": True, "host_tests": True, "hardware": False}


def test_manifest_does_not_trust_an_image_changed_since_the_build(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    fake_build(fw)
    (fw / "build" / "nvs_config.bin").write_bytes(b"edited")
    man, _ = esp32_manifest.derive(fw)
    assert man["verified"]["build"] is False
    assert man["verified"]["host_tests"] is False        # esp32_test never ran here


def test_manifest_check_says_stale_until_written(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    fake_build(fw)
    args = ["--workspace", str(ws), "--out", str(fw / "m.json")]
    assert esp32_manifest.main([*args, "--check"]) == 1
    assert esp32_manifest.main(args) == 0
    assert esp32_manifest.main([*args, "--check"]) == 0


def test_manifest_selftest_follows_the_component_header(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    fake_build(fw)
    st = esp32_manifest.derive(fw)[0]["selftest"]
    assert [c["send"].split()[1] for c in st["commands"]] == ["rails", "pd", "tone", "net"]
    assert st["commands"][2]["args"] == {"tap": "^[A-Za-z0-9_]{1,15}$", "hz": [20, 20000],
                                         "dbfs": [-60.0, 0.0]}
    assert st["ready"] is False                          # core/ only, no glue yet
    (fw / "components" / "fwe_selftest" / "fwe_selftest_idf.c").write_text("\n")
    assert esp32_manifest.derive(fw)[0]["selftest"]["ready"] is True
    shutil.rmtree(fw / "components" / "fwe_selftest")       # the scaffold's copy, not the template
    assert "selftest" not in esp32_manifest.derive(fw)[0]


def test_module_sizes_from_the_ordering_code():
    assert esp32_manifest.module("ESP32-WROVER-E-N16R8")["flash_mb"] == 16
    assert esp32_manifest.module("ESP32-WROOM-32E-N4")["psram_mb"] == 0
    assert esp32_manifest.module("ESP32-WROVER-E")["flash_mb"] is None


def test_s3_board_gets_no_template_and_no_xtensa_manifest(tmp_path):
    ws = write_board(tmp_path, base_nets(), {"U1": "ESP32-S3-WROOM-1-N16R8", "U2": "PCM5102A"})
    rc, res = fw_scaffold.scaffold(ws, fetch=False)
    assert rc == 2 and "ESP32-S3" in res["error"]
    assert not (ws / "firmware" / "components").exists()
    fw = ws / "firmware"
    fw.mkdir(exist_ok=True)
    (fw / "pinmap.json").write_text(json.dumps({"board": "PCB-9998", "mcu": {"part": "ESP32-S3-WROOM-1"}}))
    man, err = esp32_manifest.derive(fw)
    assert man is None and "classic ESP32" in err


def test_partition_sizes_as_the_table_prints_them_become_numbers():
    assert esp32_build._hex_size("64K") == "0x10000"
    assert esp32_build._hex_size("1M") == "0x100000"
    assert esp32_build._hex_size("0x2000") == "0x2000"


def test_manifest_drops_evidence_when_settings_or_sources_changed_after(board):
    ws, _, _ = board
    fw = ws / "firmware"
    fw_scaffold.scaffold(ws, fetch=False)
    fake_build(fw)
    esp32_test.main(["--workspace", str(ws), "--out", str(fw / "t.json")])
    assert esp32_manifest.derive(fw)[0]["verified"]["build"] is True
    csv_file = fw / "gen" / "nvs_config.csv"
    csv_file.write_text(csv_file.read_text() + "autoexec,data,string,1\n")
    core = fw / "components" / "fwe_stub" / "core" / "fwe_stub.c"
    core.write_text(core.read_text() + "\n")
    man, _ = esp32_manifest.derive(fw)
    assert man["verified"]["build"] is False             # the image holds the old settings
    assert man["verified"]["host_tests"] is False        # they passed on other sources


def test_scaffold_finishes_a_first_checkout_that_was_cut_short(board):
    ws, pin, _ = board
    up = ws / "firmware" / "upstream"
    git(ws, "clone", "-q", "--no-checkout", pin["repo"], str(up))   # HEAD at the tip, no tree
    pin["commit"] = git(up, "rev-parse", "HEAD")
    rc, res = fw_scaffold.scaffold(ws)
    assert rc == 0, res
    assert (up / "components" / "squeezelite" / "CMakeLists.txt").is_file()


def test_links_prune_a_removed_component_and_refuse_to_shadow_upstream(board):
    ws, _, _ = board
    fw, up = ws / "firmware", ws / "firmware" / "upstream"
    fw_scaffold.scaffold(ws)
    (fw / "components" / "fwe_extra").mkdir()
    assert "fwe_extra" in upstream.link_components(fw)
    (fw / "components" / "fwe_extra").rmdir()
    assert "fwe_extra" not in upstream.link_components(fw)
    assert not (up / "components" / "fwe_extra").is_symlink()
    assert "/components/fwe_extra" not in (up / ".git" / "info" / "exclude").read_text()
    (up / "components" / "fwe_new").mkdir()
    (fw / "components" / "fwe_new").mkdir()
    rc, res = fw_scaffold.scaffold(ws)
    assert rc == 2 and "fwe_new" in res["error"]
