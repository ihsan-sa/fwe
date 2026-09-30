#!/usr/bin/env python3
"""fw_test.py - build and run a firmware project's host unit tests.

Each <workspace>/firmware/tests/test_*.c is a standalone program over the
pure-C control code: it is compiled with the host C compiler as

  cc -std=c11 -Wall -Wextra -Werror -O1 -Icontrol -Igen -Iconfig \
     tests/test_X.c control/*.c -lm

and run; exit 0 is a pass. These tests prove the control math (Clarke/Park,
SVPWM duty, current-sense scaling, fault latching) on the host, not the
firmware on the chip.

  fw_test.py --workspace PCB-0018-A_bldc-motor-driver [--only foc]

JSON to stdout (or --out): {"ok", "cc", "tests": [{name, status:
pass|fail|compile_error, log_tail}], "passed", "failed"}. Exit 0 all pass,
1 a test failed or did not compile, 2 error (no tests, no host compiler).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402

FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-Icontrol", "-Igen", "-Iconfig"]


def tail(text: str, n: int = 30) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def run_tests(fw: Path, only: list[str], timeout: float) -> tuple[int, dict]:
    # gcc before cc: on the box ~/bin/cc is the session launcher, not a compiler
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    tests = sorted((fw / "tests").glob("test_*.c"))
    if only:
        tests = [t for t in tests if t.stem.removeprefix("test_") in only]
    if not cc or not tests:
        return 2, {"ok": False, "error": "no host C compiler" if not cc
                   else f"no tests/test_*.c in {fw}"}
    control = sorted(str(p.relative_to(fw)) for p in (fw / "control").glob("*.c"))
    out = []
    with tempfile.TemporaryDirectory(prefix="fwe-test-") as tmp:
        for t in tests:
            exe = Path(tmp) / t.stem
            p = subprocess.run([cc, *FLAGS, str(t.relative_to(fw)), *control, "-lm", "-o", str(exe)],
                               cwd=fw, capture_output=True, text=True)
            if p.returncode != 0:
                out.append({"name": t.stem, "status": "compile_error",
                            "log_tail": tail(p.stdout + p.stderr)})
                continue
            try:
                r = subprocess.run([str(exe)], cwd=fw, capture_output=True, text=True,
                                   timeout=timeout)
                status, log = ("pass" if r.returncode == 0 else "fail"), r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                status, log = "fail", f"timed out after {timeout:g} s"
            out.append({"name": t.stem, "status": status, "log_tail": tail(log)})
    failed = sum(1 for t in out if t["status"] != "pass")
    return (1 if failed else 0), {"ok": not failed, "cc": cc, "tests": out,
                                  "passed": len(out) - failed, "failed": failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workspace", required=True, help="board workspace (path, or name under boards root)")
    ap.add_argument("--only", action="append", default=[], help="run test_<name>.c only (repeatable)")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds per test program")
    ap.add_argument("--out", help="write the JSON result here instead of stdout")
    a = ap.parse_args(argv)
    fw = fwenv.workspace(a.workspace) / "firmware"
    if not fw.is_dir():
        rc, res = 2, {"ok": False, "error": f"no firmware project at {fw}"}
    else:
        rc, res = run_tests(fw, a.only, a.timeout)
    fwenv.emit(res, a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
