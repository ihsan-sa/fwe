"""Real board workspaces for the few tests that need one.

Boards are hwde's and live in their own repo, found through HWDE_BOARDS_ROOT
(default ~/dev/boards) exactly as the skill finds them (fwenv.workspace). A
test that needs a real board runs when the boards repo is there and SKIPS
with the reason when it is not: never a silent pass, never a failure on a
machine without the boards. Anything a small fixture can stand in for uses
the fixture instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))

from fwelib import fwenv  # noqa: E402


def board_path(name: str) -> Path:
    """Where board `name` lives (may not exist): a directory under the boards
    root, or the bare name of a numbered <PN>_<name> workspace."""
    return fwenv.workspace(name)


def need_board(*names: str) -> None:
    """Skip the calling test unless every named board is in the boards repo."""
    gone = [n for n in names if not board_path(n).is_dir()]
    if gone:
        pytest.skip(f"needs the real board(s) {', '.join(gone)} from the "
                    f"boards repo ({fwenv.boards_root()}; set HWDE_BOARDS_ROOT)")
