#!/usr/bin/env python3
"""fw_build.py - cross-build a board's firmware with warnings as errors.

Runs in order, stopping at the first failure:
  1. pinmap.py --check: firmware pins must still match the board's netlist
     (drift is a finding: regenerate with pinmap.py, then review the diff);
  2. CMake configure (Ninja, cmake/arm-gcc.cmake) with the pinned CMSIS
     sources from reference/toolchain.lock.json;
  3. the build. The template's flags carry -Werror, so a warning fails it.

Outputs land in <workspace>/firmware/build/: fw.elf, fw.bin, fw.hex, fw.map.

  fw_build.py --workspace PCB-0018-A_bldc-motor-driver [--stage bringup]

JSON to stdout (or --out): {"ok", "step", "version", "stage", "artifacts":
{name: {path, sha256}}, "size": {text, data, bss}, "log_tail"}. Exit 0 built,
1 drift or a failed configure/compile (the step says which), 2 error (the
toolchain or CMSIS is not installed: run fwe_setup.py).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402
from fw_scaffold import run_pinmap  # noqa: E402


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def version(ws: Path, base: str) -> str:
    p = subprocess.run(["git", "-C", str(ws), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return f"{base}+g{p.stdout.strip()}" if p.returncode == 0 and p.stdout.strip() else base


def tail(text: str, n: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def build(ws: Path, stage: str, base: str, clean: bool) -> tuple[int, dict]:
    fw = ws / "firmware"
    if not (fw / "CMakeLists.txt").is_file():
        return 2, {"ok": False, "error": f"no firmware project in {fw}: run fw_scaffold.py"}
    env = fwenv.tool_env()
    need = [shutil.which(t, path=env["PATH"]) for t in ("arm-none-eabi-gcc", "cmake", "ninja")]
    core, dev = fwenv.source("cmsis-core"), fwenv.source("cmsis-device-g4")
    if not all(need) or not core.is_dir() or not dev.is_dir():
        return 2, {"ok": False, "error": "toolchain or CMSIS missing: run fwe_setup.py"}
    rc, pm = run_pinmap(ws, "--check")
    if rc != 0:
        return (2 if rc == 2 else 1), {"ok": False, "step": "pinmap",
                                       "drift": pm.get("drift"), "findings": pm.get("findings"),
                                       "error": pm.get("error")}
    ver = version(ws, base)
    out = fw / "build"
    if clean and out.is_dir():
        shutil.rmtree(out)
    cfg = ["cmake", "-G", "Ninja", "-S", str(fw), "-B", str(out),
           "-DCMAKE_TOOLCHAIN_FILE=cmake/arm-gcc.cmake",
           f"-DFWE_CMSIS_CORE={core / 'CMSIS' / 'Core' / 'Include'}",
           f"-DFWE_CMSIS_DEVICE={dev}", f"-DFWE_VERSION={ver}", f"-DFWE_STAGE={stage}"]
    res = {"ok": False, "version": ver, "stage": stage}
    for step, cmd in (("configure", cfg), ("compile", ["cmake", "--build", str(out)])):
        p = subprocess.run(cmd, cwd=fw, env=env, capture_output=True, text=True)
        log = p.stdout + p.stderr
        if p.returncode != 0:
            return 1, {**res, "step": step, "log_tail": tail(log)}
    arts = {n: out / f"fw.{n}" for n in ("elf", "bin", "hex", "map")}
    missing = [n for n, p in arts.items() if not p.is_file()]
    if missing:
        return 1, {**res, "step": "artifacts", "error": f"not produced: {missing}"}
    size = {}
    p = subprocess.run(["arm-none-eabi-size", str(arts["elf"])], env=env,
                       capture_output=True, text=True)
    m = re.search(r"^\s*(\d+)\s+(\d+)\s+(\d+)", p.stdout, re.M)
    if m:
        size = dict(zip(("text", "data", "bss"), map(int, m.groups())))
    return 0, {**res, "ok": True, "step": "done", "size": size,
               "artifacts": {n: {"path": str(p.relative_to(fw)), "sha256": sha256(p)}
                             for n, p in arts.items() if n != "map"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--stage", default="bringup", help="firmware stage baked into the banner")
    ap.add_argument("--base-version", default="0.1.0", help="version before the +g<sha> suffix")
    ap.add_argument("--clean", action="store_true", help="delete firmware/build first")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    ws = fwenv.workspace(a.workspace)
    if not ws.is_dir():
        rc, res = 2, {"ok": False, "error": f"no workspace {ws}"}
    else:
        rc, res = build(ws, a.stage, a.base_version, a.clean)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
