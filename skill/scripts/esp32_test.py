#!/usr/bin/env python3
"""esp32_test.py - host unit tests for our ESP32 components' logic.

Each tests/host/test_*.c in the board's firmware is compiled with the host
gcc (or clang) against every components/fwe_*/core/*.c (the logic that needs no
ESP-IDF), the components' include/ dirs and firmware/gen/, with -Wall
-Wextra -Werror and libm, then run. A test passes when it exits 0. Upstream squeezelite-esp32 is never
built here.

  esp32_test.py --workspace PCB-0029-A_hifi-lite

JSON to stdout (or --out): {"ok", "tests": [{name, ok, output}], "core",
"inputs_sha256"}, also kept in firmware/build/fwe_host_tests.json.
inputs_sha256 covers every file under components/fwe_* and tests/host, so
esp32_manifest.py can tell a result from older sources.
Exit 0 all pass, 1 a test failed to build or run, 2 error (no tests, no cc).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-g"]


def inputs_hash(fw: Path) -> str:
    """sha256 over the paths and contents of our components and host tests."""
    h = hashlib.sha256()
    files = [*(fw / "components").glob("fwe_*/**/*"), *(fw / "tests" / "host").glob("**/*")]
    for f in sorted(p for p in files if p.is_file()):
        h.update(str(f.relative_to(fw)).encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def run(fw: Path) -> tuple[int, dict]:
    # gcc or clang by name: on the box `cc` is the session tool, not a compiler
    cc = shutil.which("gcc") or shutil.which("clang")
    tests = sorted((fw / "tests" / "host").glob("test_*.c"))
    if not cc or not tests:
        return 2, {"ok": False, "error": "no host gcc or clang" if not cc else f"no tests in {fw / 'tests' / 'host'}"}
    comps = sorted(d for d in (fw / "components").glob("fwe_*") if d.is_dir())
    core = [str(c) for d in comps for c in sorted((d / "core").glob("*.c"))]
    incs = [f"-I{d / 'include'}" for d in comps if (d / "include").is_dir()]
    gen = fw / "gen"
    if gen.is_dir():
        incs.append(f"-I{gen}")
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for t in tests:
            exe = Path(tmp) / t.stem
            p = subprocess.run([cc, *FLAGS, *incs, str(t), *core, "-lm", "-o", str(exe)],
                               capture_output=True, text=True)
            if p.returncode:
                out.append({"name": t.stem, "ok": False, "output": ("build: " + p.stderr)[-1500:]})
                continue
            p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            out.append({"name": t.stem, "ok": p.returncode == 0, "output": (p.stdout + p.stderr)[-1500:]})
    ok = all(t["ok"] for t in out)
    return (0 if ok else 1), {"ok": ok, "tests": out, "core": [str(Path(c).relative_to(fw)) for c in core],
                              "inputs_sha256": inputs_hash(fw)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    fw = fwenv.workspace(a.workspace) / "firmware"
    if not fw.is_dir():
        rc, res = 2, {"ok": False, "error": f"no {fw}: run fw_scaffold.py first"}
    else:
        rc, res = run(fw)
        (fw / "build").mkdir(exist_ok=True)       # the evidence esp32_manifest.py reads
        fwenv.emit(res, str(fw / "build" / "fwe_host_tests.json"))
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
