#!/usr/bin/env python3
"""Generate a terminal demo SVG for re:trace — no external tools required.

Produces docs/examples/terminal_demo.svg showing a realistic
`retrace scan board_photo.jpg` session with colorized ANSI output.
"""

from __future__ import annotations

import html
from pathlib import Path

# ---------------------------------------------------------------------------
# Terminal content — mirrors actual retrace CLI output format
# ---------------------------------------------------------------------------

# Each line is (text, color) where color is an SVG fill value.
# None → default terminal foreground (#e2e8f0)

TERM_LINES: list[tuple[str, str | None]] = [
    # prompt
    ("$ retrace scan board_photo.jpg --output ./results", "#a3e635"),
    ("", None),
    # header banner
    ("  re:trace v0.1.0 — PCB Reverse Engineering Toolkit", "#60a5fa"),
    ("  " + "─" * 50, "#4b5563"),
    ("", None),
    # detect phase
    ("[detect]   Scanning board_photo.jpg ...", "#facc15"),
    ("[detect]   Found 177 components", "#a3e635"),
    ("           ↳ 20 ICs  · 8 connectors  · 56 caps  · 29 resistors  · 64 other", "#94a3b8"),
    ("", None),
    # ocr phase
    ("[ocr]      Reading IC markings ...", "#facc15"),
    ("[ocr]      Read 18 markings — 16 matched (89%)", "#a3e635"),
    ("           ↳ Intel Atom C2508 · Xilinx XC6SLX9 · W25Q128JV · MT47H64M16 ...", "#94a3b8"),
    ("", None),
    # trace phase
    ("[trace]    Extracting copper traces ...", "#facc15"),
    ("[trace]    Extracted 88 traces · 269 nodes · 12 junctions", "#a3e635"),
    ("", None),
    # constraint solver
    ("[infer]    AC-3 constraint solver — 88 iterations", "#facc15"),
    ("[infer]    3 inferred connections · 0 conflicts · 2 ambiguous nodes", "#a3e635"),
    ("", None),
    # debug interfaces — HIGH finding
    ("[security] Scanning for exposed debug interfaces ...", "#facc15"),
    ("[security] 2 findings", "#f87171"),
    ("", None),
    ("  [HIGH]   CVSS 7.6  JTAG — full CPU debug/program access", "#f87171"),
    ("           Component: J15  (marking: JTAG)  ·  CWE-1191", "#94a3b8"),
    ("           ATT&CK: T0819 (Exploit Public-Facing Application)", "#94a3b8"),
    ("", None),
    ("  [MEDIUM] CVSS 6.8  UART — may expose bootloader or root shell", "#fb923c"),
    ("           Component: J10  (marking: CONSOLE)  ·  CWE-1299", "#94a3b8"),
    ("", None),
    # probe advisor
    ("[advise]   Bayesian probe advisor — ranked by Expected Information Gain", "#facc15"),
    ("", None),
    ("  #1  U1.DDR3_DQ0      EIG: 4.807 bits  (resolves ~4.81 bits of uncertainty)", "#e2e8f0"),
    ("  #2  U1.DDR3_A0       EIG: 4.807 bits", "#94a3b8"),
    ("  #3  U1.PCIE_TX0      EIG: 4.807 bits", "#94a3b8"),
    ("", None),
    # export
    ("[export]   Writing results to ./results/ ...", "#facc15"),
    ("[export]   annotated.svg · attack_surface.svg · zones.svg · bom.json", "#a3e635"),
    ("", None),
    # final summary line
    ("  Done.  177 components · 88 traces · 2 security findings → ./results/", "#60a5fa"),
    ("", None),
    # next prompt
    ("$ ", "#a3e635"),
]

# ---------------------------------------------------------------------------
# SVG rendering constants
# ---------------------------------------------------------------------------

WIDTH = 800
PADDING_X = 24
PADDING_Y = 20
CHROME_H = 36          # title bar height
FONT_SIZE = 13
LINE_HEIGHT = 20
FONT_FAMILY = "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Courier New', monospace"

BG_COLOR = "#0f172a"        # dark navy background
CHROME_COLOR = "#1e293b"    # slightly lighter for title bar
DOT_COLORS = ["#ef4444", "#f59e0b", "#22c55e"]  # red/yellow/green traffic lights
DEFAULT_FG = "#e2e8f0"      # default text color


def _escape(text: str) -> str:
    return html.escape(text)


def build_svg() -> str:
    content_height = len(TERM_LINES) * LINE_HEIGHT + PADDING_Y * 2
    total_height = CHROME_H + content_height

    lines_svg: list[str] = []
    y = CHROME_H + PADDING_Y + FONT_SIZE  # baseline of first line

    for text, color in TERM_LINES:
        fill = color if color else DEFAULT_FG
        escaped = _escape(text)
        lines_svg.append(
            f'    <text x="{PADDING_X}" y="{y}" fill="{fill}">{escaped}</text>'
        )
        y += LINE_HEIGHT

    lines_block = "\n".join(lines_svg)

    # Traffic light dots
    dots = ""
    for i, dot_color in enumerate(DOT_COLORS):
        cx = 16 + i * 20
        dots += f'<circle cx="{cx}" cy="{CHROME_H // 2}" r="6" fill="{dot_color}"/>\n    '

    # Title text centred in chrome
    title_y = CHROME_H // 2 + 5
    title = f'<text x="{WIDTH // 2}" y="{title_y}" fill="#94a3b8" text-anchor="middle" font-size="13">retrace — board_photo.jpg</text>'

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg"\n'
        f'     width="{WIDTH}" height="{total_height}"\n'
        f'     viewBox="0 0 {WIDTH} {total_height}">\n'
        "\n"
        "  <!-- terminal window chrome -->\n"
        f'  <rect width="{WIDTH}" height="{total_height}" rx="10" ry="10" fill="{BG_COLOR}"/>\n'
        f'  <rect width="{WIDTH}" height="{CHROME_H}" rx="10" ry="10" fill="{CHROME_COLOR}"/>\n'
        "  <!-- square off the bottom corners of the chrome bar -->\n"
        f'  <rect y="{CHROME_H // 2}" width="{WIDTH}" height="{CHROME_H // 2}" fill="{CHROME_COLOR}"/>\n'
        "\n"
        "  <!-- traffic light dots -->\n"
        f"  <g>\n    {dots}\n  </g>\n"
        "\n"
        "  <!-- window title -->\n"
        f"  {title}\n"
        "\n"
        "  <!-- terminal body -->\n"
        f"  <g font-family={FONT_FAMILY!r} font-size=\"{FONT_SIZE}\">\n"
        f"{lines_block}\n"
        "  </g>\n"
        "\n"
        "</svg>\n"
    )
    return svg


def main() -> None:
    out_path = Path(__file__).parent.parent / "docs" / "examples" / "terminal_demo.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    svg = build_svg()
    out_path.write_text(svg, encoding="utf-8")

    # Basic validity check: must start with XML declaration and contain <svg
    content = out_path.read_text()
    assert content.startswith("<?xml"), "SVG missing XML declaration"
    assert "<svg " in content, "SVG element not found"
    assert "</svg>" in content, "SVG closing tag not found"
    # +1 for the window title <text> element
    assert content.count("<text") == len(TERM_LINES) + 1, (
        f"Expected {len(TERM_LINES) + 1} <text> elements, "
        f"got {content.count('<text')}"
    )

    lines_rendered = len(TERM_LINES)
    print(f"[ok] terminal_demo.svg written — {lines_rendered} lines, {len(content):,} bytes")
    print(f"     → {out_path}")


if __name__ == "__main__":
    main()
