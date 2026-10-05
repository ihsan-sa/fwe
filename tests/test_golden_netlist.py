"""fwe's side of the golden netlist contract (tests/golden/netlist/README.md):
the copied reader makes of hwde's export exactly what hwde's reader makes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))

from fwelib.netlist import parse_netlist  # noqa: E402

GOLD = Path(__file__).resolve().parent / "golden" / "netlist"


def test_reader_matches_hwde_on_the_golden_export():
    expected = json.loads((GOLD / "usbbuck4.parsed.json").read_text(encoding="utf-8"))
    got = parse_netlist(GOLD / "usbbuck4.net")
    assert got == expected
    # node order is part of the contract (export order), and == on dicts
    # ignores key order but not list order, so this pins it too
    assert len(got["components"]) >= 20
    assert any(n["pinfunction"] for ns in got["nets"].values() for n in ns)
