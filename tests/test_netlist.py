"""fwelib: the stdlib netlist reader and the board workspace lookup.

Each case builds its own files under tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))

from fwelib import fwenv  # noqa: E402
from fwelib.netlist import NetlistError, parse_netlist  # noqa: E402


def test_parse_reads_components_nets_and_escapes(tmp_path):
    f = tmp_path / "b.net"
    f.write_text('(export (version "E")\n'
                 ' (components (comp (ref "R1") (value "10k \\"1%\\"") (footprint "R_0603")))\n'
                 ' (nets (net (code "1") (name "/VBUS")\n'
                 '   (node (ref "R1") (pin "1") (pinfunction "A") (pintype "passive"))\n'
                 '   (node (ref "U1") (pin "7")))))\n')
    nl = parse_netlist(f)
    assert nl["components"] == {"R1": {"value": '10k "1%"', "footprint": "R_0603"}}
    assert nl["nets"]["/VBUS"] == [
        {"ref": "R1", "pin": "1", "pintype": "passive", "pinfunction": "A"},
        {"ref": "U1", "pin": "7", "pintype": "", "pinfunction": ""}]


@pytest.mark.parametrize("text,why", [
    ('(kicad_sch (version 1))', "not a kicadsexpr export"),
    ('(export (nets (net (name "x"))', "does not parse"),
    ('(export) )', "does not parse"),
])
def test_parse_refuses_what_is_not_a_netlist(tmp_path, text, why):
    f = tmp_path / "b.net"
    f.write_text(text)
    with pytest.raises(NetlistError, match=why):
        parse_netlist(f)


def test_parse_missing_file_is_a_netlist_error(tmp_path):
    with pytest.raises(NetlistError, match="cannot read"):
        parse_netlist(tmp_path / "none.net")


def test_boards_root_follows_hwde_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("AIEE_BOARDS_ROOT", raising=False)
    monkeypatch.setenv("HWDE_BOARDS_ROOT", str(tmp_path))
    assert fwenv.boards_root() == tmp_path
    monkeypatch.delenv("HWDE_BOARDS_ROOT")
    assert fwenv.boards_root() == Path("~/dev/boards").expanduser()


def test_workspace_finds_bare_and_numbered_names(tmp_path, monkeypatch):
    monkeypatch.setenv("HWDE_BOARDS_ROOT", str(tmp_path))
    (tmp_path / "plain").mkdir()
    (tmp_path / "PCB-0018-A_motor").mkdir()
    assert fwenv.workspace("plain") == tmp_path / "plain"
    assert fwenv.workspace("motor") == tmp_path / "PCB-0018-A_motor"
    assert fwenv.workspace("PCB-0018-A_motor") == tmp_path / "PCB-0018-A_motor"
    assert fwenv.workspace(str(tmp_path / "plain")) == tmp_path / "plain"
    assert not fwenv.workspace("absent").exists()


def test_workspace_never_guesses_between_two_revisions(tmp_path, monkeypatch):
    monkeypatch.setenv("HWDE_BOARDS_ROOT", str(tmp_path))
    (tmp_path / "PCB-0008-A_buck").mkdir()
    (tmp_path / "PCB-0008-B_buck").mkdir()
    assert fwenv.workspace("buck") == tmp_path / "buck"
    assert not fwenv.workspace("buck").exists()
