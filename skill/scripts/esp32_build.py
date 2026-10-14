#!/usr/bin/env python3
"""esp32_build.py - build an ESP32 board's squeezelite-esp32 firmware with our components.

Runs in order, stopping at the first failure:
  1. pinmap.py --check: gen/ must still match the board's netlist;
  2. upstream: firmware/upstream must be at the lock's pinned commit (made by
     fw_scaffold.py; this step never moves it), and our components/fwe_* are
     linked into it again so a component added since the scaffold is built;
  3. idf.py build in the pinned ESP-IDF, the way upstream's CI does it
     (build-scripts/<PLATFORM>-sdkconfig.defaults, -DDEPTH=16), except that
     the sdkconfig and build dir are firmware/build/, never upstream's tree.
     PLATFORM comes from firmware/sdkconfig.fwe, which is applied after the
     platform defaults. Our components carry -Wall -Wextra -Werror in their
     own CMakeLists.txt; upstream keeps its flags. The step then checks every
     fwe_* source was compiled with -Werror;
  4. the NVS image: gen/nvs_config.csv through ESP-IDF's nvs_partition_gen.py,
     sized and placed as upstream's partition table's "settings" partition.

  esp32_build.py --workspace PCB-0029-A_hifi-lite [--platform I2S-4MFlash]

JSON to stdout (or --out): {"ok", "step", "platform", "upstream", "werror",
"sdkconfig": {platform, sdkconfig_fwe_sha256, regenerated},
"artifacts": {file: {path, sha256}}, "flash": [[offset, file], ...] (files
relative to firmware/build/), "flash_options", "nvs_csv_sha256",
"log_tail"}. Once firmware/build/ exists it is also kept there as
fwe_build.json, the evidence esp32_manifest.py reads. Exit 0 built, 1 drift,
upstream elsewhere or a failed build
(the step says which), 2 error (ESP-IDF not installed, no scaffold).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv, upstream  # noqa: E402
from fw_scaffold import run_pinmap  # noqa: E402
from fwe_setup import _framework_ok  # noqa: E402

DEFAULT_PLATFORM = "I2S-4MFlash"
NVS_PARTITION = "settings"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def platform(fw: Path, override: str | None) -> str:
    if override:
        return override
    cfg = fw / "sdkconfig.fwe"
    m = re.search(r"^#\s*PLATFORM=(\S+)", cfg.read_text(), re.M) if cfg.is_file() else None
    return m.group(1) if m else DEFAULT_PLATFORM


def sdkconfig_key(fw: Path, plat: str) -> dict:
    """What build/sdkconfig was generated from; it is only made again when it is missing."""
    cfg = fw / "sdkconfig.fwe"
    return {"platform": plat, "sdkconfig_fwe_sha256": sha256(cfg) if cfg.is_file() else None}


def drop_stale_sdkconfig(bdir: Path, key: dict) -> bool:
    """Remove build/sdkconfig when the last build's fwe_build.json shows another key (or none),
    so a changed --platform or sdkconfig.fwe is applied rather than silently ignored."""
    sdk = bdir / "sdkconfig"
    if not sdk.is_file():
        return False
    last = bdir / "fwe_build.json"
    try:
        prev = json.loads(last.read_text()).get("sdkconfig") if last.is_file() else None
    except ValueError:
        prev = None
    if isinstance(prev, dict) and all(prev.get(k) == v for k, v in key.items()):
        return False
    sdk.unlink()
    return True


def idf(env: dict, *args: str, cwd: Path, timeout: int = 5400) -> subprocess.CompletedProcess:
    """A command in the pinned ESP-IDF's environment (export.sh sets PATH and the python env)."""
    cmd = f". \"$IDF_PATH/export.sh\" >/dev/null && {shlex.join(args)}"
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def werror_sources(build: Path) -> tuple[list[str], list[str]]:
    """(fwe_* sources compiled with -Werror, those compiled without)."""
    ok, bad = [], []
    cc = build / "compile_commands.json"
    for e in json.loads(cc.read_text()) if cc.is_file() else []:
        src = e["file"]
        if "/components/fwe_" not in src:
            continue
        cmd = e.get("command") or " ".join(e.get("arguments", []))
        (ok if "-Werror" in cmd.split() else bad).append(src)
    return ok, bad


def _hex_size(size: str) -> str:
    """gen_esp32part.py prints sizes as 64K or 1M; nvs_partition_gen.py wants a number."""
    mult = {"K": 1024, "M": 1024 * 1024}.get(size[-1:].upper(), 1)
    return hex(int(size.rstrip("KkMm"), 0) * mult)


def partition(build: Path, env: dict, name: str) -> tuple[str, str] | None:
    """(offset, size in hex) of a partition in the built partition table."""
    pt = build / "partition_table" / "partition-table.bin"
    p = idf(env, "python", f"{env['IDF_PATH']}/components/partition_table/gen_esp32part.py",
            str(pt), cwd=build, timeout=120)
    if p.returncode:
        raise RuntimeError(f"gen_esp32part.py: {(p.stderr or p.stdout).strip()[-300:]}")
    for row in csv.reader(io.StringIO(p.stdout)):
        if row and not row[0].startswith("#") and row[0].strip() == name:
            return row[3].strip(), _hex_size(row[4].strip())
    return None


def flash_args(text: str) -> tuple[list[str], list[list[str]]]:
    """(options, [[offset, file], ...]) from idf.py's flash_project_args: the
    --flash_mode/--flash_freq/--flash_size options come before the first offset."""
    toks = text.split()
    first = next((i for i, t in enumerate(toks) if t.startswith("0x")), len(toks))
    return toks[:first], [[o, f] for o, f in zip(toks[first::2], toks[first + 1::2]) if o.startswith("0x")]


def _tail(out) -> str:
    """Output a timed-out subprocess caught so far (bytes or str, or None)."""
    return out.decode(errors="replace") if isinstance(out, bytes) else (out or "")


def build(ws: Path, plat_arg: str | None) -> tuple[int, dict]:
    fw = ws / "firmware"
    res: dict = {"ok": False}
    rc, pm = run_pinmap(ws, "--check")
    if rc:
        return (2 if rc == 2 else 1), {**res, "step": "pinmap", "pinmap": pm}
    up = fw / "upstream"
    u = upstream.entry()
    have = upstream.head(up) if (up / ".git").exists() else None
    if have is None:
        return 2, {**res, "step": "upstream", "error": f"no {up}: run fw_scaffold.py first"}
    res["upstream"] = {"commit": have, "pinned": u["commit"]}
    if have != u["commit"]:
        return 1, {**res, "step": "upstream",
                   "fix": "run fw_scaffold.py --update to check out the lock's commit"}
    try:
        upstream.link_components(fw)
    except ValueError as e:
        return 2, {**res, "step": "upstream", "error": str(e)}

    entry = fwenv.framework("esp-idf")
    env = fwenv.idf_env(entry)
    installed, why = _framework_ok(entry)
    if not installed:
        return 2, {**res, "step": "idf", "error": f"{why}: run fwe_setup.py --only esp-idf"}
    plat = platform(fw, plat_arg)
    res["platform"] = plat
    defaults = up / "build-scripts" / f"{plat}-sdkconfig.defaults"
    if not defaults.is_file():
        return 2, {**res, "step": "idf", "error": f"upstream has no {defaults.name}"}
    bdir = fw / "build"
    bdir.mkdir(exist_ok=True)
    key = sdkconfig_key(fw, plat)
    res["sdkconfig"] = {**key, "regenerated": drop_stale_sdkconfig(bdir, key)}
    sdk_defaults = [str(defaults)] + ([str(fw / "sdkconfig.fwe")] if (fw / "sdkconfig.fwe").is_file() else [])
    try:
        p = idf(env, "idf.py", "-C", str(up), "-B", str(bdir), f"-DSDKCONFIG={bdir / 'sdkconfig'}",
                f"-DSDKCONFIG_DEFAULTS={';'.join(sdk_defaults)}", "-DDEPTH=16", "build", cwd=fw)
        log, failed = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        log, failed = _tail(e.stdout) + _tail(e.stderr) + f"\nfwe: idf.py build timed out after {e.timeout}s\n", 1
        res["error"] = f"idf.py build timed out after {e.timeout}s"
    (bdir / "fwe_build.log").write_text(log)
    res["log_tail"] = log.strip().splitlines()[-25:]
    if failed:
        return 1, {**res, "step": "build"}

    ok, bad = werror_sources(bdir)
    res["werror"] = {"checked": len(ok), "without": bad}
    if bad or not ok:
        return 1, {**res, "step": "werror"}

    try:
        part = partition(bdir, env, NVS_PARTITION)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        return 1, {**res, "step": "nvs", "error": str(e)}
    if not part:
        return 1, {**res, "step": "nvs", "error": f"no {NVS_PARTITION} partition in the table"}
    nvs_bin = bdir / "nvs_config.bin"
    nvs_bin.unlink(missing_ok=True)
    try:
        p = idf(env, "python", f"{env['IDF_PATH']}/components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py",
                "generate", str(fw / "gen" / "nvs_config.csv"), str(nvs_bin), part[1], cwd=fw, timeout=120)
    except subprocess.TimeoutExpired as e:
        return 1, {**res, "step": "nvs", "error": f"nvs_partition_gen.py timed out after {e.timeout}s"}
    if p.returncode or not nvs_bin.is_file():   # it exits 0 on a bad argument
        return 1, {**res, "step": "nvs", "log_tail": (p.stdout + p.stderr).strip().splitlines()[-15:]}

    flash = []
    fa = bdir / "flash_project_args"
    if fa.is_file():
        res["flash_options"], flash = flash_args(fa.read_text())   # options as idf.py flashes
    res["flash"] = flash + [[part[0], str(nvs_bin.relative_to(bdir))]]
    res["nvs_csv_sha256"] = sha256(fw / "gen" / "nvs_config.csv")
    res["artifacts"] = {f: {"path": str(bdir / f), "sha256": sha256(bdir / f)}
                        for _, f in res["flash"] if (bdir / f).is_file()}
    return 0, {**res, "ok": True, "step": "done"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--platform", help="upstream build-scripts platform (default: sdkconfig.fwe's PLATFORM)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not (ws / "firmware").is_dir():
        rc, res = 2, {"ok": False, "error": f"no {ws / 'firmware'}: run fw_scaffold.py first"}
    else:
        rc, res = build(ws, a.platform)
        if (ws / "firmware" / "build").is_dir():   # the evidence esp32_manifest.py reads
            fwenv.emit(res, str(ws / "firmware" / "build" / "fwe_build.json"))
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
