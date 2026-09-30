"""fwelib/netlist.py - read a KiCad (kicadsexpr) netlist export, stdlib only.

parse_netlist() returns the same shape as hwde's lib/simlib.parse_netlist
(https://github.com/ihsan-sa/hwde), which /fwe used before it left hwde:

  {"components": {ref: {"value", "footprint"}},
   "nets": {name: [{"ref", "pin", "pintype", "pinfunction"}]}}

The reader here is a small s-expression tokenizer so the skill needs no
third-party package to run.
"""
from __future__ import annotations

import re
from pathlib import Path


class NetlistError(RuntimeError):
    """The netlist cannot be read or is not a kicadsexpr export."""


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def _parse(text: str) -> list:
    stack: list[list] = [[]]
    pos = 0
    while True:
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise NetlistError(f"unexpected text at offset {pos}")
            break
        pos = m.end()
        opn, cls, quoted, atom = m.groups()
        if opn:
            stack.append([])
        elif cls:
            if len(stack) == 1:
                raise NetlistError(f"unbalanced ')' at offset {pos}")
            done = stack.pop()
            stack[-1].append(done)
        elif quoted is not None:
            stack[-1].append(re.sub(r"\\(.)", r"\1", quoted))
        else:
            stack[-1].append(atom)
    if len(stack) != 1:
        raise NetlistError("unbalanced '(': the file ends inside a list")
    top = stack[0]
    if len(top) != 1 or not isinstance(top[0], list):
        raise NetlistError("expected exactly one top-level list")
    return top[0]


def _kids(node: list, tag: str) -> list[list]:
    return [k for k in node if isinstance(k, list) and k and k[0] == tag]


def _atom(node: list, tag: str, default=None):
    for k in _kids(node, tag):
        if len(k) > 1 and not isinstance(k[1], list):
            return str(k[1])
    return default


def parse_netlist(path: Path | str) -> dict:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise NetlistError(f"cannot read netlist {p}: {exc}") from exc
    try:
        data = _parse(text)
    except NetlistError as exc:
        raise NetlistError(f"netlist {p} does not parse: {exc}") from exc
    if not data or data[0] != "export":
        raise NetlistError(f"netlist {p}: not a kicadsexpr export")
    comps: dict[str, dict] = {}
    for blk in _kids(data, "components"):
        for c in _kids(blk, "comp"):
            ref = _atom(c, "ref")
            if ref:
                comps[ref] = {"value": _atom(c, "value"),
                              "footprint": _atom(c, "footprint")}
    nets: dict[str, list] = {}
    for blk in _kids(data, "nets"):
        for n in _kids(blk, "net"):
            name = _atom(n, "name")
            if name is None:
                continue
            nets[name] = [{"ref": _atom(nd, "ref"), "pin": _atom(nd, "pin"),
                           "pintype": _atom(nd, "pintype", ""),
                           "pinfunction": _atom(nd, "pinfunction", "")}
                          for nd in _kids(n, "node")]
    return {"components": comps, "nets": nets}
