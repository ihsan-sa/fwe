"""fwelib/gateware.py - an FPGA project's config, geometry and tools.

An FPGA board's gateware lives in its workspace as firmware/ (where the
boards seat's handoff README lands too), described by firmware/gateware.json
(templates/fpga/gateware.json). The core is board-independent; `board`
holds what only the chosen dev board knows, and stays null until the
handoff README fills it.

The simulators and yosys come from chip-flow's `bin/eda` (the IIC-OSIC-TOOLS
tree /vde runs on, CHIP_FLOW_HOME, default ~/.claude/skills/chip-flow); a
tool missing there is looked up on PATH.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

BOARD_KEYS = ("model", "vendor", "part", "package", "ref_clk_hz", "ref_clk_pin",
              "pwm_pins", "io_standard", "uart_rx_pin", "uart_tx_pin")
SIM_CPB = 8   # UART clocks per bit in simulation, so a bench runs in seconds


def chip_flow() -> Path:
    return Path(os.environ.get("CHIP_FLOW_HOME") or Path.home() / ".claude" / "skills" / "chip-flow")


def eda() -> Path:
    return chip_flow() / "bin" / "eda"


def tool(name: str) -> list[str] | None:
    """The argv prefix that runs `name`: through eda when its tree has it,
    else from PATH, else None."""
    if eda().is_file():
        p = subprocess.run([str(eda()), name, "--version"], capture_output=True, text=True)
        if "don't know how to run" not in p.stderr:
            return [str(eda()), name]
    found = shutil.which(name)
    return [found] if found else None


def load(fw: Path) -> dict:
    return json.loads((fw / "gateware.json").read_text(encoding="utf-8"))


def geometry(cfg: dict) -> dict:
    """What the steps mean in time, and whether the core accepts them."""
    n, w, f = cfg["steps_per_period"], cfg["word_bits"], cfg["f_rf_hz"]
    line = n * f
    fabric = line / w
    problems = []
    if n % w:
        problems.append(f"steps_per_period {n} is not a multiple of word_bits {w}")
    if not 2 <= n <= 255:
        problems.append(f"steps_per_period {n} outside 2..255 (one register byte)")
    if cfg["channels"] != 8:
        problems.append("the pwm8 design has 8 channels")
    pw = max(1, n.bit_length())
    return {"steps_per_period": n, "word_bits": w, "phase_bits": pw,
            "step_s": 1 / line, "line_rate_bps": line, "fabric_clk_hz": fabric,
            "uart_cpb": round(fabric / cfg["uart_baud"]), "problems": problems}


def board_missing(cfg: dict) -> list[str]:
    b = cfg.get("board") or {}
    gone = [k for k in BOARD_KEYS if not b.get(k)]
    if b.get("pwm_pins") and len(b["pwm_pins"]) != cfg["channels"]:
        gone.append(f"pwm_pins ({len(b['pwm_pins'])} of {cfg['channels']})")
    return gone


def sources(fw: Path, *dirs: str) -> list[Path]:
    return sorted(p for d in dirs for p in (fw / d).glob("*.v"))


def design_hash(fw: Path) -> str:
    """sha256 over the config, RTL and bench: a recorded result counts only
    while this is unchanged."""
    h = hashlib.sha256()
    files = [fw / "gateware.json", *sources(fw, "rtl", "tb"), *sorted((fw / "tb").glob("*.py"))]
    for p in files:
        if p.is_file():
            h.update(str(p.relative_to(fw)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def record(fw: Path, name: str, res: dict) -> None:
    out = fw / "build" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**res, "design_sha256": design_hash(fw)}, indent=2) + "\n",
                   encoding="utf-8")


def recorded_ok(fw: Path, name: str) -> bool:
    p = fw / "build" / f"{name}.json"
    if not p.is_file():
        return False
    r = json.loads(p.read_text(encoding="utf-8"))
    return bool(r.get("ok")) and r.get("design_sha256") == design_hash(fw)
