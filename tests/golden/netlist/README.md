# Golden netlist (hwde -> fwe contract)

Both files are copies of ai-ee's `tests/golden/netlist/` at ai-ee commit
82e242b (PR #73). `usbbuck4.net` is the kicadsexpr netlist hwde exports for its
golden schematic, and `usbbuck4.parsed.json` is what hwde's own reader,
`lib/simlib.parse_netlist`, makes of it.

`tests/test_golden_netlist.py` holds fwe's copy of that reader
(`skill/scripts/fwelib/netlist.py`) to the same JSON, so the two readers can't
drift apart. When hwde regenerates its golden files (a new KiCad or a changed
schematic), copy both here again and update the commit above; never edit them
by hand.
