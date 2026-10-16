"""fwe_webapp's phone page against the API its core/ answers.

The page hard-codes each control's key and range, so this reads the core's FIELDS
and INPUTS tables (and the defines they use) and checks the page offers exactly
those keys, inputs and ranges, and calls only the route the core handles.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "skill" / "templates" / "esp32" / "components"
WEBAPP = COMPONENTS / "fwe_webapp"


def defines() -> dict[str, int]:
    """The integer #defines of the headers FIELDS uses, casts and f/u suffixes dropped."""
    out: dict[str, int] = {}
    for h in (WEBAPP / "include" / "fwe_webapp.h", COMPONENTS / "fwe_xover" / "include" / "fwe_xover.h"):
        for name, val in re.findall(r"^#define (FWE_\w+) ([^/\n]+)", h.read_text(), re.M):
            m = re.fullmatch(r"\(?(-?\d+)(?:\.0)?[fu]?\)?", val.strip())
            if m:
                out[name] = int(m.group(1))
    return out


def value(expr: str, defs: dict[str, int]) -> int:
    expr = re.sub(r"\(int32_t\)", "", expr).strip()
    neg = expr.startswith("-")
    expr = expr.lstrip("-")
    v = defs[expr] if expr in defs else int(expr)
    return -v if neg else v


def core_api() -> tuple[dict[str, tuple[int, int]], list[str]]:
    src = (WEBAPP / "core" / "fwe_webapp.c").read_text()
    defs = defines()
    fields = {key: (value(lo, defs), value(hi, defs))
              for key, lo, hi in re.findall(r'\{"(\w+)", ([^,]+), ([^,]+), "bad \w+"\}', src)}
    inputs = re.findall(r'"(\w+)"', re.search(r"INPUTS\[FWE_INPUT_COUNT\] = \{([^}]*)\}", src).group(1))
    return fields, inputs


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.controls: dict[str, dict[str, str]] = {}
        self.options: list[str] = []
        self.script = ""
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-key" in a:
            assert a["data-key"] not in self.controls, f"two controls for {a['data-key']}"
            self.controls[a["data-key"]] = {"tag": tag, **a}
        if tag == "option":
            self.options.append(a["value"])
        self._in_script = tag == "script"

    def handle_endtag(self, tag):
        self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.script += data


def test_page_offers_each_setting_the_core_has_at_its_range():
    fields, inputs = core_api()
    assert len(fields) == 9 and inputs == ["lms", "airplay", "bt", "spotify"]   # the parse found them
    page = Page()
    page.feed((WEBAPP / "page" / "index.html").read_text())
    assert set(page.controls) == {"input", *fields}
    assert page.controls["input"]["tag"] == "select" and page.options == inputs
    for key, (lo, hi) in fields.items():
        c = page.controls[key]
        assert (int(c["min"]), int(c["max"])) == (lo, hi), key
    assert set(re.findall(r'"(/api/[^"]*)"', page.script)) == {"/api/settings"}
