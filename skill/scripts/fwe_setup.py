#!/usr/bin/env python3
"""fwe_setup.py - install or check /fwe's pinned toolchain in user space.

Reads reference/toolchain.lock.json. Each tarball is downloaded into
<tools>/dl/, its sha256 checked against the lock (a mismatch is an error and
nothing is extracted), and unpacked into <tools>/<name>-<version>/. Each
source is a sparse, shallow git fetch of the pinned commit into
<tools>/src/<name>-<version>/, re-fetched when the lock's commit or paths
change or a pinned path is gone; a tree whose .fwe-commit holds only the
commit (written before the marker listed paths) counts as present when every
pinned path is there. A framework (ESP-IDF, for the esp32 target) is a
shallow clone of its pinned tag with submodules into <tools>/<name>-<version>/,
checked to be the pinned commit, then IDF's own idf_tools.py installs the
compilers for the pinned targets and its python env (on the python the lock
names, from uv) into <tools>/espressif/. Frameworks are big (about 2 GB), so
they install only when asked for: --only esp-idf, or --frameworks.
<tools> is FWE_TOOLS_DIR, default ~/.local/fwe-tools. Nothing needs root; no
apt, no containers.

Usage:
  fwe_setup.py            install whatever is missing, then check
  fwe_setup.py --check    only check (exit 1 when something is missing)
  fwe_setup.py --only NAME [--only NAME]
  fwe_setup.py --frameworks       also ESP-IDF (the esp32 target)

JSON to stdout (or --out): {"ok", "tools_dir", "items": [{name, version,
status: ok|missing|installed|error, detail}]}. Exit 0 all present, 1 some
missing (--check), 2 an install failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fwelib import fwenv  # noqa: E402


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(entry: dict) -> tuple[bool, str]:
    exe = fwenv.tool_root(entry) / entry["bin"] / entry["probe"][0]
    if not exe.exists():
        return False, f"{exe} missing"
    try:
        r = subprocess.run([str(exe), *entry["probe"][1:]], capture_output=True,
                           text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{exe}: {exc}"
    line = (r.stdout or r.stderr).strip().splitlines()
    return r.returncode == 0, line[0] if line else f"rc={r.returncode}"


def _install_tarball(entry: dict) -> str:
    dl = fwenv.tools_dir() / "dl"
    dl.mkdir(parents=True, exist_ok=True)
    tgz = dl / entry["url"].rsplit("/", 1)[1]
    if not tgz.exists() or _sha256(tgz) != entry["sha256"]:
        with urllib.request.urlopen(entry["url"], timeout=600) as r, open(tgz, "wb") as fh:
            shutil.copyfileobj(r, fh)
    got = _sha256(tgz)
    if got != entry["sha256"]:
        tgz.unlink()
        raise RuntimeError(f"sha256 mismatch for {tgz.name}: {got}")
    dest = fwenv.tool_root(entry)
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(tgz) as tf:
        tf.extractall(tmp, filter="tar")
    kids = list(tmp.iterdir())
    top = kids[0] if len(kids) == 1 and kids[0].is_dir() else tmp
    shutil.rmtree(dest, ignore_errors=True)
    top.rename(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return f"unpacked {tgz.name}"


def _marker(entry: dict) -> str:
    """The pinned commit and paths: a lock that adds a path re-fetches the tree."""
    return "\n".join([entry["commit"], *entry["paths"]]) + "\n"


def _source_ok(entry: dict) -> bool:
    """The tree is at the pinned commit and holds every pinned path. Read the
    marker as _marker() writes it, and also in its older form (the commit
    alone, before the paths were added), which trees fetched then still carry:
    for those the paths on disk decide. A marker that lists paths must list
    every path the lock pins, so a lock that adds one re-fetches."""
    root = fwenv.source_root(entry)
    mark = root / ".fwe-commit"
    if not mark.is_file():
        return False
    lines = mark.read_text().split("\n")
    lines = [ln for ln in lines if ln]
    if not lines or lines[0] != entry["commit"]:
        return False
    if len(lines) > 1 and not set(entry["paths"]) <= set(lines[1:]):
        return False
    return all((root / p).exists() for p in entry["paths"])


def _install_source(entry: dict) -> str:
    root = fwenv.source_root(entry)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    git = ["git", "-C", str(root)]
    steps = [
        ["git", "init", "-q", str(root)],
        git + ["remote", "add", "origin", entry["repo"]],
        git + ["sparse-checkout", "set", "--no-cone", *entry["paths"]],
        git + ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", entry["commit"]],
        git + ["checkout", "-q", "FETCH_HEAD"],
    ]
    for cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise RuntimeError(f"{' '.join(cmd[3:5])}: {r.stderr.strip()[:300]}")
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    if head != entry["commit"]:
        raise RuntimeError(f"checked out {head}, lock says {entry['commit']}")
    (root / ".fwe-commit").write_text(_marker(entry))
    return f"checked out {entry['commit'][:12]}"


def _framework_marker(entry: dict) -> str:
    """What a finished install wrote: a changed commit, target, python or extra re-installs."""
    return "\n".join([entry["commit"], ",".join(entry["targets"]), entry["python"],
                      *entry.get("python_extra", [])]) + "\n"


def _framework_ok(entry: dict) -> tuple[bool, str]:
    root = fwenv.framework_root(entry)
    mark = root / ".fwe-installed"
    if not (root / "tools" / "idf.py").is_file():
        return False, f"{root} missing"
    if not mark.is_file() or mark.read_text() != _framework_marker(entry):
        return False, f"{root}: not installed at {entry['commit'][:12]} for {entry['targets']}"
    return True, f"{entry['version']} at {entry['commit'][:12]}, targets {','.join(entry['targets'])}"


def _run(cmd: list[str], env: dict | None = None, timeout: int = 3600) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd[:4])}: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout.strip()


def _install_framework(entry: dict) -> str:
    """Clone the pinned tag with submodules, check the commit, then let IDF's
    idf_tools.py fetch its compilers and build its python env, as upstream's
    Dockerfile does. The marker is written last, so a half install re-runs."""
    root = fwenv.framework_root(entry)
    part = root.with_name(root.name + ".part")
    shutil.rmtree(part, ignore_errors=True)
    _run(["git", "clone", "-q", "--depth", "1", "--branch", entry["tag"], "--recursive",
          "--shallow-submodules", "-j", "8", entry["repo"], str(part)])
    head = _run(["git", "-C", str(part), "rev-parse", "HEAD"])
    if head != entry["commit"]:
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError(f"tag {entry['tag']} is {head}, lock says {entry['commit']}")
    shutil.rmtree(root, ignore_errors=True)
    part.rename(root)
    if not shutil.which("uv"):
        raise RuntimeError(f"uv not on PATH, needed for python {entry['python']}")
    _run(["uv", "python", "install", entry["python"]])      # a no-op when present
    py = _run(["uv", "python", "find", entry["python"]])
    env = fwenv.idf_env(entry)
    tools = [py, str(root / "tools" / "idf_tools.py"), "--non-interactive"]
    _run(tools + ["install", "--targets=" + ",".join(entry["targets"]), "required"], env)
    _run(tools + ["install", "cmake"], env)
    # IDF wants the virtualenv package on the base python to make its env, and
    # pip-installs it --user when it is missing, which uv's python refuses. A
    # seeded uv venv at the path IDF computes is one it accepts and fills.
    venv = fwenv.idf_python_env(entry)
    if not (venv / "bin" / "python").exists():
        _run(["uv", "venv", "-q", "--seed", "--python", py, str(venv)])
    _run(tools + ["install-python-env"], env)
    # Upstream's CI image adds these to IDF's env (its Dockerfile, unpinned): cspot's
    # nanopb generator imports google.protobuf. The lock pins what resolved.
    if entry.get("python_extra"):
        _run([str(venv / "bin" / "python"), "-m", "pip", "install", "-q", *entry["python_extra"]])
    (root / ".fwe-installed").write_text(_framework_marker(entry))
    return f"cloned {entry['tag']} and installed its tools with python {entry['python']}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="check only, install nothing")
    ap.add_argument("--only", action="append", default=[], help="limit to these names")
    ap.add_argument("--frameworks", action="store_true",
                    help="also the frameworks (ESP-IDF), which install only when asked")
    ap.add_argument("--out", help="write the JSON here instead of stdout")
    a = ap.parse_args(argv)
    lk = fwenv.lock()
    items, failed, missing = [], False, False
    probe = {"tarball": _probe, "source": lambda e: (_source_ok(e), ""),
             "framework": _framework_ok}
    install = {"tarball": _install_tarball, "source": _install_source,
               "framework": _install_framework}
    for kind, entries in (("tarball", lk["tarballs"]), ("source", lk["sources"]),
                          ("framework", lk.get("frameworks", []))):
        for e in entries:
            if a.only and e["name"] not in a.only:
                continue
            if kind == "framework" and not (a.frameworks or e["name"] in a.only):
                continue
            it = {"name": e["name"], "version": e["version"], "kind": kind}
            present, detail = probe[kind](e)
            if present:
                it.update(status="ok", detail=detail)
            elif a.check:
                it.update(status="missing", detail=detail)
                missing = True
            else:
                try:
                    note = install[kind](e)
                    ok, detail = probe[kind](e)
                    it.update(status="installed" if ok else "error", detail=detail or note)
                    failed |= not ok
                except Exception as exc:  # report every item, fail at the end
                    it.update(status="error", detail=str(exc)[:400])
                    failed = True
            items.append(it)
    res = {"ok": not (failed or missing), "tools_dir": str(fwenv.tools_dir()), "items": items}
    text = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 2 if failed else (1 if missing else 0)


if __name__ == "__main__":
    sys.exit(main())
