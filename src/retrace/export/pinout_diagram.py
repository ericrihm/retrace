"""Pinout diagram generator — crops debug headers from board images, annotates pin assignments."""

from __future__ import annotations

import base64
import html as html_mod
from pathlib import Path
from typing import Any, Optional

from retrace.core.pipeline import AnalysisResult, Component

# ── Pin assignments per interface type and pin count ─────────────────
# Each pin: (name, function_group, description)

_PINOUTS: dict[str, dict[int, list[tuple[str, str, str]]]] = {
    "JTAG": {
        20: [
            ("VTref", "power", "Target reference voltage"),
            ("VCC", "power", "Target supply"),
            ("nTRST", "control", "Test reset (active low)"),
            ("GND", "ground", "Ground"),
            ("TDI", "data", "Test data in"),
            ("GND", "ground", "Ground"),
            ("TMS", "control", "Test mode select"),
            ("GND", "ground", "Ground"),
            ("TCK", "clock", "Test clock"),
            ("GND", "ground", "Ground"),
            ("RTCK", "clock", "Return test clock"),
            ("GND", "ground", "Ground"),
            ("TDO", "data", "Test data out"),
            ("GND", "ground", "Ground"),
            ("RESET", "control", "System reset"),
            ("GND", "ground", "Ground"),
            ("DBGRQ", "debug", "Debug request"),
            ("GND", "ground", "Ground"),
            ("DBGACK", "debug", "Debug acknowledge"),
            ("GND", "ground", "Ground"),
        ],
        14: [
            ("VTref", "power", "Target reference voltage"),
            ("VCC", "power", "Target supply"),
            ("nTRST", "control", "Test reset"),
            ("GND", "ground", "Ground"),
            ("TDI", "data", "Test data in"),
            ("GND", "ground", "Ground"),
            ("TMS", "control", "Test mode select"),
            ("GND", "ground", "Ground"),
            ("TCK", "clock", "Test clock"),
            ("GND", "ground", "Ground"),
            ("TDO", "data", "Test data out"),
            ("GND", "ground", "Ground"),
            ("RESET", "control", "System reset"),
            ("GND", "ground", "Ground"),
        ],
        10: [
            ("VTref", "power", "Target reference voltage"),
            ("TMS/SWDIO", "control", "Test mode / SWD data"),
            ("GND", "ground", "Ground"),
            ("TCK/SWCLK", "clock", "Test clock / SWD clock"),
            ("GND", "ground", "Ground"),
            ("TDO/SWO", "data", "Data out / SWD trace"),
            ("KEY", "control", "Keyed (no connect)"),
            ("TDI", "data", "Test data in"),
            ("GND", "ground", "Ground"),
            ("RESET", "control", "System reset"),
        ],
    },
    "SWD": {
        10: [
            ("VTref", "power", "Target reference voltage"),
            ("SWDIO", "data", "Serial wire data I/O"),
            ("GND", "ground", "Ground"),
            ("SWCLK", "clock", "Serial wire clock"),
            ("GND", "ground", "Ground"),
            ("SWO", "data", "Serial wire output (trace)"),
            ("KEY", "control", "Keyed (no connect)"),
            ("NC", "control", "Not connected"),
            ("GND", "ground", "Ground"),
            ("RESET", "control", "System reset"),
        ],
        4: [
            ("SWCLK", "clock", "Serial wire clock"),
            ("SWDIO", "data", "Serial wire data I/O"),
            ("GND", "ground", "Ground"),
            ("VCC", "power", "Supply voltage"),
        ],
        2: [
            ("SWCLK", "clock", "Serial wire clock"),
            ("SWDIO", "data", "Serial wire data I/O"),
        ],
    },
    "UART": {
        4: [
            ("VCC", "power", "Supply (3.3V or 5V)"),
            ("TX", "data", "Transmit → host"),
            ("RX", "data", "Receive ← host"),
            ("GND", "ground", "Ground"),
        ],
        3: [
            ("TX", "data", "Transmit → host"),
            ("RX", "data", "Receive ← host"),
            ("GND", "ground", "Ground"),
        ],
        6: [
            ("GND", "ground", "Ground"),
            ("CTS", "control", "Clear to send"),
            ("VCC", "power", "Supply voltage"),
            ("TX", "data", "Transmit → host"),
            ("RX", "data", "Receive ← host"),
            ("RTS", "control", "Request to send"),
        ],
    },
    "SPI": {
        8: [
            ("VCC", "power", "Supply voltage"),
            ("HOLD", "control", "Hold (active low)"),
            ("WP", "control", "Write protect"),
            ("GND", "ground", "Ground"),
            ("CS", "control", "Chip select (active low)"),
            ("MOSI", "data", "Master out, slave in"),
            ("MISO", "data", "Master in, slave out"),
            ("SCLK", "clock", "Serial clock"),
        ],
        6: [
            ("VCC", "power", "Supply voltage"),
            ("GND", "ground", "Ground"),
            ("CS", "control", "Chip select"),
            ("MOSI", "data", "Master out, slave in"),
            ("MISO", "data", "Master in, slave out"),
            ("SCLK", "clock", "Serial clock"),
        ],
        4: [
            ("CS", "control", "Chip select"),
            ("MOSI", "data", "Master out, slave in"),
            ("MISO", "data", "Master in, slave out"),
            ("SCLK", "clock", "Serial clock"),
        ],
    },
    "I2C": {
        4: [
            ("VCC", "power", "Supply voltage"),
            ("SCL", "clock", "Serial clock"),
            ("SDA", "data", "Serial data"),
            ("GND", "ground", "Ground"),
        ],
        2: [
            ("SCL", "clock", "Serial clock"),
            ("SDA", "data", "Serial data"),
        ],
    },
}

# ── Probe wiring guides ─────────────────────────────────────────────

_PROBE_GUIDES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "JTAG": {
        "J-Link / Segger": [
            ("VTref", "Pin 1 (VTref)"),
            ("nTRST", "Pin 3 (nTRST)"),
            ("TDI", "Pin 5 (TDI)"),
            ("TMS", "Pin 7 (TMS)"),
            ("TCK", "Pin 9 (TCK)"),
            ("TDO", "Pin 13 (TDO)"),
            ("RESET", "Pin 15 (nRESET)"),
            ("GND", "Pin 4 (GND)"),
        ],
        "Bus Pirate": [
            ("TDI", "MOSI"),
            ("TDO", "MISO"),
            ("TCK", "CLK"),
            ("TMS", "CS"),
            ("GND", "GND"),
        ],
        "OpenOCD + FTDI": [
            ("TCK", "ADBUS0"),
            ("TDI", "ADBUS1"),
            ("TDO", "ADBUS2"),
            ("TMS", "ADBUS3"),
            ("GND", "GND"),
        ],
    },
    "SWD": {
        "J-Link / Segger": [
            ("SWDIO", "Pin 7 (SWDIO)"),
            ("SWCLK", "Pin 9 (SWCLK)"),
            ("SWO", "Pin 13 (SWO)"),
            ("RESET", "Pin 15 (nRESET)"),
            ("VTref", "Pin 1 (VTref)"),
            ("GND", "Pin 4 (GND)"),
        ],
        "ST-Link V2": [
            ("SWDIO", "Pin 2 (SWDIO)"),
            ("SWCLK", "Pin 6 (SWCLK)"),
            ("RESET", "Pin 15 (NRST)"),
            ("GND", "Pin 3 (GND)"),
        ],
    },
    "UART": {
        "FTDI FT232 / FT2232": [
            ("TX (target)", "RXD (FTDI)"),
            ("RX (target)", "TXD (FTDI)"),
            ("GND", "GND"),
        ],
        "Bus Pirate": [
            ("TX (target)", "MISO (BP)"),
            ("RX (target)", "MOSI (BP)"),
            ("GND", "GND"),
        ],
    },
    "SPI": {
        "Bus Pirate": [
            ("MOSI", "MOSI (BP)"),
            ("MISO", "MISO (BP)"),
            ("SCLK", "CLK (BP)"),
            ("CS", "CS (BP)"),
            ("GND", "GND"),
        ],
        "FTDI FT232H": [
            ("SCLK", "ADBUS0 (TCK)"),
            ("MOSI", "ADBUS1 (TDI)"),
            ("MISO", "ADBUS2 (TDO)"),
            ("CS", "ADBUS3 (TMS)"),
            ("GND", "GND"),
        ],
        "flashrom": [
            ("CS", "chip pin 1"),
            ("MISO", "chip pin 2 (DO)"),
            ("MOSI", "chip pin 5 (DI)"),
            ("SCLK", "chip pin 6 (CLK)"),
            ("VCC", "chip pin 8"),
            ("GND", "chip pin 4"),
        ],
    },
    "I2C": {
        "Bus Pirate": [
            ("SCL", "CLK (BP)"),
            ("SDA", "MOSI (BP)"),
            ("GND", "GND"),
        ],
        "FTDI FT232H": [
            ("SCL", "ADBUS0"),
            ("SDA", "ADBUS1 + ADBUS2"),
            ("GND", "GND"),
        ],
    },
}

_UART_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# ── Color scheme ─────────────────────────────────────────────────────

_GROUP_COLORS: dict[str, str] = {
    "data": "#3b82f6",
    "clock": "#22c55e",
    "power": "#ef4444",
    "ground": "#6b7280",
    "control": "#f59e0b",
    "debug": "#a855f7",
}

_BG = "#0a0e1a"
_PANEL_BG = "#111827"
_PANEL_BORDER = "#1e293b"
_TEXT_HI = "#e2e8f0"
_TEXT_MID = "#94a3b8"
_TEXT_LO = "#64748b"
_ACCENT = "#22d3ee"
_FONT = "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace"


def _esc(text: str) -> str:
    return html_mod.escape(str(text))


def _q(s: str) -> str:
    return f'"{s}"'


# ── Pin layout calculation ───────────────────────────────────────────

def _is_dual_row(interface: str, pin_count: int) -> bool:
    if pin_count <= 3:
        return False
    if interface in ("JTAG", "SWD") and pin_count >= 10:
        return True
    return pin_count >= 6


def _best_pinout(interface: str, pin_count: int) -> list[tuple[str, str, str]]:
    iface_pins = _PINOUTS.get(interface, {})
    if not iface_pins:
        return [("?", "control", f"Pin {i + 1}") for i in range(pin_count)]
    if pin_count in iface_pins:
        return iface_pins[pin_count]
    available = sorted(iface_pins.keys())
    closest = min(available, key=lambda k: abs(k - pin_count))
    pins = list(iface_pins[closest])
    if len(pins) < pin_count:
        for i in range(len(pins), pin_count):
            pins.append(("NC", "control", f"Pin {i + 1}"))
    return pins[:pin_count]


def _pin_positions_in_crop(
    comp_x_in_crop: int,
    comp_y_in_crop: int,
    comp_w: int,
    comp_h: int,
    pin_count: int,
    dual_row: bool,
) -> list[tuple[int, int]]:
    """Calculate pin center coordinates relative to the crop image."""
    positions: list[tuple[int, int]] = []

    if dual_row:
        cols = 2
        rows = (pin_count + 1) // 2
        row_spacing = comp_h / (rows + 1)
        col_inset = int(comp_w * 0.15)

        for pin_idx in range(pin_count):
            row = pin_idx // 2
            col = pin_idx % 2
            px = comp_x_in_crop + col_inset + col * (comp_w - 2 * col_inset)
            py = comp_y_in_crop + row_spacing * (row + 1)
            positions.append((int(px), int(py)))
    else:
        vertical = comp_h > comp_w
        if vertical:
            spacing = comp_h / (pin_count + 1)
            for i in range(pin_count):
                px = comp_x_in_crop + comp_w // 2
                py = comp_y_in_crop + spacing * (i + 1)
                positions.append((int(px), int(py)))
        else:
            spacing = comp_w / (pin_count + 1)
            for i in range(pin_count):
                px = comp_x_in_crop + spacing * (i + 1)
                py = comp_y_in_crop + comp_h // 2
                positions.append((int(px), int(py)))

    return positions


# ── Image cropping ───────────────────────────────────────────────────

def _crop_to_base64(
    image_path: str,
    bbox: tuple[int, int, int, int],
    padding_factor: float = 0.5,
) -> tuple[Optional[str], tuple[int, int, int, int]]:
    """Crop around bbox with padding, return (base64_png, crop_bbox).

    crop_bbox is (crop_x, crop_y, crop_w, crop_h) in original image coords.
    """
    try:
        from PIL import Image

        img = Image.open(image_path)
        iw, ih = img.size
    except Exception:
        return None, (0, 0, 0, 0)

    x, y, w, h = bbox
    pad_x = int(w * padding_factor)
    pad_y = int(h * padding_factor)

    crop_x = max(0, x - pad_x)
    crop_y = max(0, y - pad_y)
    crop_x2 = min(iw, x + w + pad_x)
    crop_y2 = min(ih, y + h + pad_y)
    crop_w = crop_x2 - crop_x
    crop_h = crop_y2 - crop_y

    cropped = img.crop((crop_x, crop_y, crop_x2, crop_y2))

    import io
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return b64, (crop_x, crop_y, crop_w, crop_h)


# ── SVG rendering ───────────────────────────────────────────────────

def _render_defs() -> str:
    return """  <defs>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000" flood-opacity="0.5"/>
    </filter>
    <marker id="pin-arrow" viewBox="0 0 10 6" refX="9" refY="3"
            markerWidth="7" markerHeight="4" orient="auto-start-reverse">
      <path d="M 0 0 L 10 3 L 0 6 z" fill="context-stroke" fill-opacity="0.8"/>
    </marker>
  </defs>"""


def _render_schematic_header(
    img_x: int,
    img_y: int,
    img_w: int,
    img_h: int,
    comp_x: int,
    comp_y: int,
    comp_w: int,
    comp_h: int,
) -> str:
    """Render a schematic header outline when no real image is available."""
    parts: list[str] = []
    parts.append(f'  <rect x="{img_x}" y="{img_y}" width="{img_w}" height="{img_h}" '
                 f'rx="4" fill="#0b1120" stroke="#1e2d40" stroke-width="1"/>')
    hx = img_x + comp_x
    hy = img_y + comp_y
    parts.append(f'  <rect x="{hx}" y="{hy}" width="{comp_w}" height="{comp_h}" '
                 f'rx="2" fill="#1a2332" stroke="#2a4060" stroke-width="1.5" '
                 f'stroke-dasharray="4,2"/>')
    parts.append(f'  <text x="{hx + comp_w // 2}" y="{hy + comp_h // 2 + 4}" '
                 f'text-anchor="middle" font-family={_q(_FONT)} font-size="9" '
                 f'fill="{_TEXT_LO}">header</text>')
    return "\n".join(parts)


def _render_pin_annotations(
    pins: list[tuple[str, str, str]],
    pin_positions: list[tuple[int, int]],
    img_x: int,
    img_y: int,
    img_w: int,
    svg_w: int,
    dual_row: bool,
) -> str:
    """Render pin dots on the image and leader lines to labels on the sides."""
    parts: list[str] = []
    label_margin = 8
    line_h = 22

    left_labels: list[tuple[int, str, str, str, int, int]] = []
    right_labels: list[tuple[int, str, str, str, int, int]] = []

    for i, ((name, group, desc), (px, py)) in enumerate(zip(pins, pin_positions)):
        pin_num = i + 1
        abs_px = img_x + px
        abs_py = img_y + py
        color = _GROUP_COLORS.get(group, "#6b7280")

        parts.append(f'  <circle cx="{abs_px}" cy="{abs_py}" r="4" '
                     f'fill="{color}" stroke="#fff" stroke-width="1" filter="url(#glow)"/>')

        if pin_num == 1:
            parts.append(f'  <rect x="{abs_px - 8}" y="{abs_py - 8}" width="16" height="16" '
                         f'rx="8" fill="none" stroke="{_ACCENT}" stroke-width="1.5" '
                         f'stroke-dasharray="3,2" opacity="0.7"/>')

        if dual_row:
            if pin_num % 2 == 1:
                left_labels.append((pin_num, name, group, desc, abs_px, abs_py))
            else:
                right_labels.append((pin_num, name, group, desc, abs_px, abs_py))
        else:
            if pin_num <= (len(pins) + 1) // 2:
                left_labels.append((pin_num, name, group, desc, abs_px, abs_py))
            else:
                right_labels.append((pin_num, name, group, desc, abs_px, abs_py))

    if left_labels:
        start_y = min(py for _, _, _, _, _, py in left_labels) - line_h // 2
        for idx, (pin_num, name, group, desc, abs_px, abs_py) in enumerate(left_labels):
            color = _GROUP_COLORS.get(group, "#6b7280")
            label_x = label_margin
            label_y = start_y + idx * line_h
            label_text = f"{pin_num}  {name}"

            parts.append(f'  <line x1="{label_x + len(label_text) * 7 + 4}" y1="{label_y}" '
                         f'x2="{abs_px}" y2="{abs_py}" '
                         f'stroke="{color}" stroke-width="1" stroke-opacity="0.5" '
                         f'marker-end="url(#pin-arrow)"/>')

            parts.append(f'  <text x="{label_x}" y="{label_y + 4}" '
                         f'font-family={_q(_FONT)} font-size="10" fill="{color}" '
                         f'font-weight="bold">{_esc(label_text)}</text>')

    if right_labels:
        start_y = min(py for _, _, _, _, _, py in right_labels) - line_h // 2
        for idx, (pin_num, name, group, desc, abs_px, abs_py) in enumerate(right_labels):
            color = _GROUP_COLORS.get(group, "#6b7280")
            label_x = svg_w - label_margin
            label_y = start_y + idx * line_h
            label_text = f"{name}  {pin_num}"

            parts.append(f'  <line x1="{abs_px}" y1="{abs_py}" '
                         f'x2="{label_x - len(label_text) * 7 - 4}" y2="{label_y}" '
                         f'stroke="{color}" stroke-width="1" stroke-opacity="0.5" '
                         f'marker-end="url(#pin-arrow)"/>')

            parts.append(f'  <text x="{label_x}" y="{label_y + 4}" '
                         f'text-anchor="end" font-family={_q(_FONT)} font-size="10" '
                         f'fill="{color}" font-weight="bold">{_esc(label_text)}</text>')

    return "\n".join(parts)


def _render_probe_guide(
    interface: str,
    svg_w: int,
    y_offset: int,
) -> tuple[str, int]:
    """Render probe wiring guide table. Returns (svg_fragment, height_used)."""
    guides = _PROBE_GUIDES.get(interface, {})
    if not guides:
        return "", 0

    parts: list[str] = []
    pad = 16
    row_h = 18
    header_h = 32
    probe_names = list(guides.keys())
    max_rows = max(len(wires) for wires in guides.values())
    panel_h = header_h + (max_rows + 1) * row_h + pad * 2
    panel_w = svg_w - pad * 2

    parts.append(f'  <g class="probe-guide" transform="translate(0, {y_offset})">')
    parts.append(f'    <rect x="{pad}" y="0" width="{panel_w}" height="{panel_h}" '
                 f'rx="6" fill="{_PANEL_BG}" stroke="{_PANEL_BORDER}" stroke-width="1" '
                 f'filter="url(#shadow)"/>')

    parts.append(f'    <text x="{pad + 12}" y="24" font-family={_q(_FONT)} '
                 f'font-size="11" fill="{_ACCENT}" font-weight="bold">'
                 f'Probe Connection Guide</text>')

    col_w = (panel_w - 24) // (len(probe_names) + 1)
    tx = pad + 12
    ty = header_h + 8

    parts.append(f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
                 f'font-size="9" fill="{_TEXT_HI}" font-weight="bold">Target Pin</text>')
    for pi, pname in enumerate(probe_names):
        px = tx + col_w * (pi + 1)
        parts.append(f'    <text x="{px}" y="{ty}" font-family={_q(_FONT)} '
                     f'font-size="9" fill="{_ACCENT}" font-weight="bold">{_esc(pname)}</text>')

    parts.append(f'    <line x1="{tx}" y1="{ty + 6}" x2="{pad + panel_w - 12}" '
                 f'y2="{ty + 6}" stroke="{_PANEL_BORDER}" stroke-width="0.5"/>')
    ty += row_h

    all_pins: dict[str, dict[str, str]] = {}
    for pname, wires in guides.items():
        for target_pin, probe_pin in wires:
            if target_pin not in all_pins:
                all_pins[target_pin] = {}
            all_pins[target_pin][pname] = probe_pin

    for target_pin, mappings in all_pins.items():
        pin_base = target_pin.split(" ")[0].upper().rstrip(")")
        group = "ground"
        if any(k in pin_base for k in ("VCC", "VT", "VDD", "3V3", "5V")):
            group = "power"
        elif any(k in pin_base for k in ("CLK", "TCK", "SCL", "SWCLK", "SCLK")):
            group = "clock"
        elif any(k in pin_base for k in ("TD", "SW", "MO", "MI", "SD", "TX", "RX")):
            group = "data"
        elif any(k in pin_base for k in ("TMS", "RST", "CS", "RESET", "NTRST", "CTS", "RTS")):
            group = "control"
        color = _GROUP_COLORS.get(group, _TEXT_MID)

        parts.append(f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
                     f'font-size="9" fill="{color}">{_esc(target_pin)}</text>')
        for pi, pname in enumerate(probe_names):
            px = tx + col_w * (pi + 1)
            probe_pin = mappings.get(pname, "—")
            parts.append(f'    <text x="{px}" y="{ty}" font-family={_q(_FONT)} '
                         f'font-size="9" fill="{_TEXT_MID}">{_esc(probe_pin)}</text>')
        ty += row_h

    parts.append('  </g>')
    return "\n".join(parts), panel_h


def _render_notes(
    interface: str,
    svg_w: int,
    y_offset: int,
) -> tuple[str, int]:
    """Render interface-specific notes (baud rates, voltage warnings)."""
    parts: list[str] = []
    pad = 16
    notes: list[str] = []

    notes.append("⚠  Verify target voltage (1.8V / 3.3V / 5V) before connecting probe")

    if interface == "UART":
        rates = ", ".join(str(r) for r in _UART_BAUD_RATES)
        notes.append(f"Common baud rates: {rates}")
        notes.append("TX/RX are labeled from the target's perspective — cross them to your adapter")
    elif interface == "JTAG":
        notes.append("Pin 1 is typically marked with a dot, square pad, or silkscreen indicator")
        notes.append("Use OpenOCD, J-Link Commander, or urjtag to verify connectivity")
    elif interface == "SWD":
        notes.append("SWD requires only SWDIO + SWCLK + GND — minimal 3-wire connection")
        notes.append("Use openocd -f interface/cmsis-dap.cfg or pyocd to connect")
    elif interface == "SPI":
        notes.append("For flash chips: hold WP and HOLD pins high, or use a clip (SOIC-8/SOIC-16)")
        notes.append("Use flashrom, spiflash, or Bus Pirate to dump firmware")
    elif interface == "I2C":
        notes.append("Scan bus with i2cdetect or Bus Pirate to enumerate devices")
        notes.append("Check for pull-up resistors on SDA/SCL (typically 4.7kΩ)")

    row_h = 18
    panel_h = pad * 2 + len(notes) * row_h + 8
    panel_w = svg_w - pad * 2

    parts.append(f'  <g class="notes" transform="translate(0, {y_offset})">')
    parts.append(f'    <rect x="{pad}" y="0" width="{panel_w}" height="{panel_h}" '
                 f'rx="6" fill="{_PANEL_BG}" stroke="#7f1d1d" stroke-width="1" '
                 f'filter="url(#shadow)"/>')

    ty = pad + 12
    for note in notes:
        parts.append(f'    <text x="{pad + 12}" y="{ty}" font-family={_q(_FONT)} '
                     f'font-size="9" fill="{_TEXT_MID}">{_esc(note)}</text>')
        ty += row_h

    parts.append('  </g>')
    return "\n".join(parts), panel_h


def _render_legend(svg_w: int, y_offset: int) -> tuple[str, int]:
    """Render color legend for pin function groups."""
    parts: list[str] = []
    items = list(_GROUP_COLORS.items())
    item_w = 90
    total_w = len(items) * item_w
    start_x = (svg_w - total_w) // 2

    parts.append(f'  <g class="legend" transform="translate(0, {y_offset})">')
    for i, (group, color) in enumerate(items):
        x = start_x + i * item_w
        parts.append(f'    <circle cx="{x + 6}" cy="10" r="4" fill="{color}"/>')
        parts.append(f'    <text x="{x + 14}" y="14" font-family={_q(_FONT)} '
                     f'font-size="9" fill="{_TEXT_MID}">{group}</text>')
    parts.append('  </g>')
    return "\n".join(parts), 28


# ── Public API ───────────────────────────────────────────────────────

def generate_pinout_svg(
    result: AnalysisResult,
    finding: dict[str, Any],
    width: int = 760,
) -> str:
    """Generate an SVG pinout diagram for a detected debug interface.

    Args:
        result: AnalysisResult from pipeline (provides image_path, components).
        finding: Debug interface finding dict with component_id, interface, etc.
        width: Total SVG width.

    Returns:
        Self-contained SVG string with embedded board image crop and pin annotations.
    """
    interface = finding.get("interface", "JTAG")
    comp_id = finding.get("component_id", "")
    comp = next((c for c in result.components if c.id == comp_id), None)

    if comp is None and result.components:
        comp = result.components[0]
    if comp is None:
        comp = Component(id="J1", label="header", confidence=0.9,
                         bbox=(100, 100, 60, 120), marking=interface)

    bbox = comp.bbox
    pin_count = _detect_pin_count(comp, interface)
    dual_row = _is_dual_row(interface, pin_count)
    pins = _best_pinout(interface, pin_count)

    label_margin = 180
    title_h = 40
    img_padding = 16
    footer_gap = 12

    crop_b64, crop_bbox = _crop_to_base64(result.image_path, bbox, padding_factor=0.5)

    if crop_b64:
        crop_x, crop_y, crop_w, crop_h = crop_bbox
        comp_x_in_crop = bbox[0] - crop_x
        comp_y_in_crop = bbox[1] - crop_y
        scale = min(1.0, (width - 2 * label_margin) / crop_w)
        disp_w = int(crop_w * scale)
        disp_h = int(crop_h * scale)
        scaled_comp_x = int(comp_x_in_crop * scale)
        scaled_comp_y = int(comp_y_in_crop * scale)
        scaled_comp_w = int(bbox[2] * scale)
        scaled_comp_h = int(bbox[3] * scale)
    else:
        disp_w = min(300, width - 2 * label_margin)
        disp_h = int(disp_w * 1.5) if dual_row else int(disp_w * 0.6)
        scaled_comp_x = int(disp_w * 0.25)
        scaled_comp_y = int(disp_h * 0.15)
        scaled_comp_w = int(disp_w * 0.5)
        scaled_comp_h = int(disp_h * 0.7)

    img_x = label_margin
    img_y = title_h + img_padding

    pin_positions = _pin_positions_in_crop(
        scaled_comp_x, scaled_comp_y, scaled_comp_w, scaled_comp_h,
        pin_count, dual_row,
    )

    content_bottom = img_y + disp_h + img_padding

    probe_svg, probe_h = _render_probe_guide(interface, width, content_bottom)
    content_bottom += probe_h + 8 if probe_h else 0

    notes_svg, notes_h = _render_notes(interface, width, content_bottom)
    content_bottom += notes_h + 8 if notes_h else 0

    legend_svg, legend_h = _render_legend(width, content_bottom)
    content_bottom += legend_h

    svg_h = content_bottom + footer_gap + 24

    comp_label = comp.marking or comp.label or comp.id
    title_text = f"{interface} Pinout — {comp_label}"
    if finding.get("cvss_base"):
        title_text += f" (CVSS {finding['cvss_base']})"

    lines: list[str] = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'width="{width}" height="{svg_h}" '
                 f'viewBox="0 0 {width} {svg_h}">')
    lines.append('  <!-- re:trace pinout diagram -->')
    lines.append(_render_defs())

    lines.append(f'  <rect width="{width}" height="{svg_h}" fill="{_BG}"/>')

    lines.append(f'  <rect width="{width}" height="{title_h}" '
                 f'fill="{_PANEL_BG}" fill-opacity="0.92"/>')
    lines.append(f'  <line x1="0" y1="{title_h}" x2="{width}" y2="{title_h}" '
                 f'stroke="{_ACCENT}" stroke-width="1" stroke-opacity="0.4"/>')
    lines.append(f'  <text x="12" y="26" font-family={_q(_FONT)} '
                 f'font-size="13" fill="{_ACCENT}" font-weight="bold">re:trace</text>')
    lines.append(f'  <text x="80" y="26" font-family={_q(_FONT)} '
                 f'font-size="11" fill="{_TEXT_HI}">{_esc(title_text)}</text>')

    if crop_b64:
        lines.append(f'  <image href="data:image/png;base64,{crop_b64}" '
                     f'x="{img_x}" y="{img_y}" width="{disp_w}" height="{disp_h}" '
                     f'preserveAspectRatio="xMidYMid meet"/>')
        lines.append(f'  <rect x="{img_x}" y="{img_y}" width="{disp_w}" height="{disp_h}" '
                     f'rx="4" fill="none" stroke="{_PANEL_BORDER}" stroke-width="1"/>')
    else:
        lines.append(_render_schematic_header(
            img_x, img_y, disp_w, disp_h,
            scaled_comp_x, scaled_comp_y, scaled_comp_w, scaled_comp_h,
        ))

    lines.append(f'  <rect x="{img_x + scaled_comp_x}" y="{img_y + scaled_comp_y}" '
                 f'width="{scaled_comp_w}" height="{scaled_comp_h}" '
                 f'rx="2" fill="none" stroke="{_ACCENT}" stroke-width="1.5" '
                 f'stroke-dasharray="4,2" opacity="0.6"/>')

    lines.append(_render_pin_annotations(
        pins, pin_positions, img_x, img_y, disp_w, width, dual_row,
    ))

    if probe_svg:
        lines.append(probe_svg)
    if notes_svg:
        lines.append(notes_svg)
    lines.append(legend_svg)

    fy = svg_h - 24
    lines.append(f'  <rect y="{fy}" width="{width}" height="24" '
                 f'fill="{_PANEL_BG}" fill-opacity="0.92"/>')
    lines.append(f'  <text x="{width // 2}" y="{fy + 16}" text-anchor="middle" '
                 f'font-family={_q(_FONT)} font-size="9" fill="{_TEXT_LO}">'
                 f're:trace pinout diagram — {_esc(interface)} {pin_count}-pin</text>')

    lines.append('</svg>')
    return "\n".join(lines)


def _detect_pin_count(comp: Component, interface: str) -> int:
    """Estimate pin count from component metadata or interface defaults."""
    marking = (comp.marking or "").lower()
    for token in marking.replace("-", " ").replace("_", " ").split():
        if token.isdigit():
            n = int(token)
            if 2 <= n <= 40:
                return n

    if comp.package:
        pkg = comp.package.lower()
        for token in pkg.replace("-", " ").split():
            if token.isdigit() and 2 <= int(token) <= 40:
                return int(token)

    iface_pins = _PINOUTS.get(interface, {})
    if iface_pins:
        return max(iface_pins.keys())

    return 10


def generate_all_pinout_svgs(
    result: AnalysisResult,
    findings: list[dict[str, Any]],
    width: int = 760,
) -> list[tuple[str, str]]:
    """Generate pinout SVGs for all debug interface findings.

    Returns:
        List of (interface_name, svg_string) tuples.
    """
    diagrams: list[tuple[str, str]] = []
    for finding in findings:
        if finding.get("type") != "debug_interface":
            continue
        interface = finding.get("interface", "unknown")
        svg = generate_pinout_svg(result, finding, width=width)
        diagrams.append((interface, svg))
    return diagrams


def save_pinout_svg(
    result: AnalysisResult,
    finding: dict[str, Any],
    output_path: str,
    **kwargs: Any,
) -> None:
    """Generate and save a pinout diagram to disk."""
    svg = generate_pinout_svg(result, finding, **kwargs)
    Path(output_path).write_text(svg, encoding="utf-8")
