"""upstream.py - an ESP32 board's squeezelite-esp32 checkout in <firmware>/upstream.

The checkout is a plain clone at the commit toolchain.lock.json pins
("upstreams"), with its submodules. Our components live beside it in
<firmware>/components/fwe_* and are linked into upstream/components/, the
links listed in upstream's .git/info/exclude, so upstream's own tree stays
clean and moving to a newer commit never meets our files. Nothing here pushes
or adds a remote: the clone's only remote is the one it came from.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import fwenv

NAME = "squeezelite-esp32"


def entry() -> dict:
    return next(u for u in fwenv.lock()["upstreams"] if u["name"] == NAME)


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def head(up: Path) -> str | None:
    p = _git("rev-parse", "HEAD", cwd=up)
    return p.stdout.strip() if p.returncode == 0 else None


def checked_out(up: Path) -> bool:
    """HEAD's whole tree is in the index and on disk (local edits aside)."""
    if _git("diff", "--cached", "--quiet", "HEAD", cwd=up).returncode:
        return False
    return not _git("ls-files", "--deleted", cwd=up).stdout.strip()


def fetch(up: Path, repo: str, commit: str, update: bool = False) -> dict:
    """Clone repo at commit into up, or check an existing clone is at it.

    An existing clone at another commit is a finding unless update is set,
    then it is checked out at the pinned commit (fetching it if missing).
    """
    fresh = not (up / ".git").exists()
    if fresh:
        up.parent.mkdir(parents=True, exist_ok=True)
        p = _git("clone", "--no-checkout", "--filter=blob:none", repo, str(up))
        if p.returncode:
            return {"ok": False, "error": f"git clone {repo}: {p.stderr.strip()[-300:]}"}
    have = head(up)
    if have != commit and not (update or fresh):
        return {"ok": False, "finding": "upstream_moved", "have": have, "pinned": commit,
                "fix": "the lock pins another commit: rerun with --update to check it out"}
    if fresh or have != commit or not checked_out(up):
        # a fresh --no-checkout clone, or one whose first checkout was cut short,
        # has HEAD at the pin but not its tree
        if _git("cat-file", "-e", f"{commit}^{{commit}}", cwd=up).returncode:
            _git("fetch", "origin", commit, cwd=up)
        p = _git("-c", "advice.detachedHead=false", "checkout", "-q", commit, cwd=up)
        if p.returncode:
            return {"ok": False, "error": f"git checkout {commit}: {p.stderr.strip()[-300:]}"}
    p = _git("submodule", "update", "--init", "--recursive", cwd=up)
    if p.returncode:
        return {"ok": False, "error": f"git submodule update: {p.stderr.strip()[-300:]}"}
    return {"ok": True, "path": str(up), "commit": head(up)}


def link_components(fw: Path) -> list[str]:
    """Link each <fw>/components/fwe_* into upstream/components and exclude the links.

    A link whose component has gone is removed with its exclude line. Raises
    ValueError when upstream has a real directory of the same name: ours would
    shadow it, which is a rename, never an overwrite."""
    up = fw / "upstream"
    exclude = up / ".git" / "info" / "exclude"
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    for old in sorted((up / "components").glob("fwe_*")):
        if old.is_symlink() and not old.exists():
            old.unlink()
            lines = [ln for ln in lines if ln != f"/components/{old.name}"]
    linked = []
    for comp in sorted((fw / "components").glob("fwe_*")):
        if not comp.is_dir():
            continue
        dst = up / "components" / comp.name
        if dst.exists() and not dst.is_symlink():
            raise ValueError(f"upstream has its own components/{comp.name}: rename ours")
        if not dst.is_symlink():
            dst.symlink_to(os.path.relpath(comp, dst.parent))
        if f"/components/{comp.name}" not in lines:
            lines.append(f"/components/{comp.name}")
        linked.append(comp.name)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(lines) + "\n")
    return linked
