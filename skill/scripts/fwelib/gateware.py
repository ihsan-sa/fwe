"""fwelib/gateware.py - an FPGA project's config, geometry and tools.

An FPGA board's gateware lives in its workspace as firmware/ (where the
boards seat's handoff README lands too), described by firmware/gateware.json
(templates/fpga/gateware.json). The core is board-independent; `board`
holds what only the chosen dev board knows, and stays null until the
handoff README fills it.

The simulators and yosys come from chip-flow's `bin/eda` (the IIC-OSIC-TOOLS
tree /vde runs on, CHIP_FLOW_HOME, default ~/.claude/skills/chip-flow); a
tool missing there is looked up in the user-level OSS CAD Suite that
fpga_setup.py --install unpacks (FWE_FPGA_TOOLS, default
~/.local/share/fwe/oss-cad-suite), then on PATH.
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
FINE_TAPS = 128   # pwm8_taps: the fine trim's range, one ECP5 DELAYF


def chip_flow() -> Path:
    return Path(os.environ.get("CHIP_FLOW_HOME") or Path.home() / ".claude" / "skills" / "chip-flow")


def eda() -> Path:
    return chip_flow() / "bin" / "eda"


def tools_home() -> Path:
    return Path(os.environ.get("FWE_FPGA_TOOLS")
                or Path.home() / ".local" / "share" / "fwe" / "oss-cad-suite")


def tool(name: str) -> list[str] | None:
    """The argv prefix that runs `name`: through eda when its tree has it,
    else from the user-level OSS CAD Suite, else from PATH, else None."""
    if eda().is_file():
        p = subprocess.run([str(eda()), name, "--version"], capture_output=True, text=True)
        if "don't know how to run" not in p.stderr:
            return [str(eda()), name]
    own = tools_home() / "bin" / name
    if own.is_file():
        return [str(own)]
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


def clocking(cfg: dict) -> dict | None:
    """What the board's two cascaded PLLs give (feedback on CLKOP, so VCO =
    PFD x CLKFB_DIV x CLKOP_DIV), and the f_rf that follows: the DDR gearbox
    sends two steps per edge-clock cycle. None without `board.pll`."""
    b = cfg.get("board") or {}
    if not b.get("pll") or not b.get("ref_clk_hz"):
        return None
    f, problems, plls = float(b["ref_clk_hz"]), [], []
    for i, p in enumerate(b["pll"], 1):
        pfd = f / p["CLKI_DIV"]
        vco = pfd * p["CLKFB_DIV"] * p["CLKOP_DIV"]
        f = vco / p["CLKOS_DIV"]
        plls.append({"pfd_hz": pfd, "vco_hz": vco, "clkos_hz": f})
        if not 10e6 <= pfd <= 400e6:
            problems.append(f"PLL{i} PFD {pfd / 1e6:.3f} MHz outside 10-400")
        if not 400e6 <= vco <= 800e6:
            problems.append(f"PLL{i} VCO {vco / 1e6:.3f} MHz outside 400-800")
    eclk = f
    line = 2 * eclk
    n, w = cfg["steps_per_period"], cfg["word_bits"]
    f_rf = line / n
    if eclk > 400e6:
        problems.append(f"edge clock {eclk / 1e6:.3f} MHz over the 400 MHz -8 limit")
    return {"plls": plls, "eclk_hz": eclk, "sclk_hz": line / w, "line_rate_bps": line,
            "step_s": 1 / line, "f_rf_hz": f_rf,
            "f_rf_ppm": (f_rf / cfg["f_rf_hz"] - 1) * 1e6,
            "uart_cpb": round(line / w / cfg["uart_baud"]), "problems": problems}


def calibration(cfg: dict) -> dict:
    """The per-channel skew trim the board was calibrated to (zeros until
    /npie measures it), checked against the registers' ranges."""
    ch, n = cfg["channels"], cfg["steps_per_period"]
    c = cfg.get("calibration") or {}
    coarse = c.get("coarse") or [0] * ch
    fine = c.get("fine") or [0] * ch
    problems = []
    if len(coarse) != ch or len(fine) != ch:
        problems.append(f"calibration needs {ch} coarse and {ch} fine values")
    problems += [f"ch{k} coarse {v} outside 0..{n - 1}" for k, v in enumerate(coarse)
                 if not 0 <= v < n]
    problems += [f"ch{k} fine {v} outside 0..{FINE_TAPS - 1}" for k, v in enumerate(fine)
                 if not 0 <= v < FINE_TAPS]
    return {"source": c.get("source"), "coarse": coarse, "fine": fine, "problems": problems}


def board_missing(cfg: dict) -> list[str]:
    b = cfg.get("board") or {}
    gone = [k for k in BOARD_KEYS if not b.get(k)]
    if b.get("pwm_pins") and len(b["pwm_pins"]) != cfg["channels"]:
        gone.append(f"pwm_pins ({len(b['pwm_pins'])} of {cfg['channels']})")
    return gone


def sources(fw: Path, *dirs: str) -> list[Path]:
    return sorted(p for d in dirs for p in (fw / d).glob("*.v"))


def design_hash(fw: Path) -> str:
    """sha256 over the config, RTL, bench and vendor files: a recorded result
    counts only while this is unchanged."""
    h = hashlib.sha256()
    files = [fw / "gateware.json", *sources(fw, "rtl", "tb"), *sorted((fw / "tb").glob("*.py")),
             *sorted((fw / "vendor").rglob("*.v"))]
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
