#!/usr/bin/env python3
"""fwe_setup.py - install or check /fwe's pinned toolchain in user space.

Reads reference/toolchain.lock.json. Each tarball is downloaded into
<tools>/dl/, its sha256 checked against the lock (a mismatch is an error and
nothing is extracted), and unpacked into <tools>/<name>-<version>/. Each
source is a sparse, shallow git fetch of the pinned commit into
<tools>/src/<name>-<version>/, re-fetched when the lock's commit or paths
change. <tools> is FWE_TOOLS_DIR, default
~/.local/fwe-tools. Nothing needs root; no apt, no containers.

Usage:
  fwe_setup.py            install whatever is missing, then check
  fwe_setup.py --check    only check (exit 1 when something is missing)
  fwe_setup.py --only NAME [--only NAME]

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
    root = fwenv.source_root(entry)
    return (root / ".fwe-commit").is_file() and \
        (root / ".fwe-commit").read_text() == _marker(entry)


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="check only, install nothing")
    ap.add_argument("--only", action="append", default=[], help="limit to these names")
    ap.add_argument("--out", help="write the JSON here instead of stdout")
    a = ap.parse_args(argv)
    lk = fwenv.lock()
    items, failed, missing = [], False, False
    for kind, entries in (("tarball", lk["tarballs"]), ("source", lk["sources"])):
        for e in entries:
            if a.only and e["name"] not in a.only:
                continue
            it = {"name": e["name"], "version": e["version"], "kind": kind}
            present, detail = _probe(e) if kind == "tarball" else (_source_ok(e), "")
            if present:
                it.update(status="ok", detail=detail)
            elif a.check:
                it.update(status="missing", detail=detail)
                missing = True
            else:
                try:
                    note = _install_tarball(e) if kind == "tarball" else _install_source(e)
                    ok, detail = _probe(e) if kind == "tarball" else (_source_ok(e), note)
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
