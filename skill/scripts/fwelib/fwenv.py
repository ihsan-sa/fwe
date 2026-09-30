"""fwelib/fwenv.py - where /fwe's pinned tools live, and where the boards are.

Tools install under FWE_TOOLS_DIR (default ~/.local/fwe-tools) from
reference/toolchain.lock.json: tarballs into <dir>/<name>-<version>/, pinned
sources into <dir>/src/<name>-<version>/. Nothing here needs root.

Board workspaces are hwde's (https://github.com/ihsan-sa/hwde): they live
under HWDE_BOARDS_ROOT, default ~/dev/boards. boards_root() is a copy of
hwde's lib/env.boards_root, so /fwe reads the same variable without importing
hwde.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
LOCK = SKILL / "reference" / "toolchain.lock.json"
_PN_DIR = re.compile(r"^PCB-\d{4}-[A-HJ-NP-Z]_(.+)$")


def tools_dir() -> Path:
    return Path(os.environ.get("FWE_TOOLS_DIR") or Path.home() / ".local" / "fwe-tools")


def lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def tool_root(entry: dict) -> Path:
    return tools_dir() / f"{entry['name']}-{entry['version']}"


def source_root(entry: dict) -> Path:
    return tools_dir() / "src" / f"{entry['name']}-{entry['version']}"


def bin_dirs() -> list[Path]:
    """The bin directory of every pinned tarball, lock order."""
    return [tool_root(t) / t["bin"] for t in lock()["tarballs"]]


def tool_env() -> dict:
    """os.environ with the pinned tools first on PATH."""
    e = dict(os.environ)
    e["PATH"] = os.pathsep.join([str(p) for p in bin_dirs()] + [e.get("PATH", "")])
    return e


def source(name: str) -> Path:
    for s in lock()["sources"]:
        if s["name"] == name:
            return source_root(s)
    raise KeyError(name)


def boards_root() -> Path:
    """HWDE_BOARDS_ROOT (or its pre-rename spelling AIEE_BOARDS_ROOT), else
    ~/dev/boards. Not validated: the caller that needs a workspace says so."""
    val = os.environ.get("HWDE_BOARDS_ROOT") or os.environ.get("AIEE_BOARDS_ROOT")
    return Path(val or "~/dev/boards").expanduser()


def workspace(arg: str) -> Path:
    """A board workspace from a path, or a name under the boards root.

    A name is a directory under the root, or the bare board name of a
    numbered workspace <PN>_<name> (PCB-0018-A_bldc-motor-driver). Two
    numbered matches are ambiguous and resolve to nothing (root/arg, which
    does not exist), never to a guess."""
    ws = Path(arg).expanduser()
    if ws.is_dir():
        return ws
    root = boards_root()
    if (root / arg).is_dir() or not root.is_dir():
        return root / arg
    hits = [d for d in root.iterdir() if d.is_dir()
            and (m := _PN_DIR.match(d.name)) and m.group(1) == arg]
    return hits[0] if len(hits) == 1 else root / arg


def emit(res: dict, out: str | None) -> None:
    """The SPEC contract's output: JSON to --out when given, else stdout."""
    text = json.dumps(res, indent=2)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
