"""SVG annotated overlay export — components, traces, BOM, net topology, security."""

from __future__ import annotations

import html
from collections import Counter
from typing import Optional

from retrace.core.pipeline import AnalysisResult, Component, Trace

# ── Dark-theme palette ──────────────────────────────────────────────────

_BG = "#0a0e1a"
_GRID = "#131a2b"
_PANEL_BG = "#111827"
_PANEL_BORDER = "#1e293b"
_TEXT_HI = "#e2e8f0"
_TEXT_MID = "#94a3b8"
_TEXT_LO = "#64748b"
_ACCENT = "#22d3ee"
_DIVIDER = "#1e293b"

_LABEL_COLORS: dict[str, str] = {
    "ic": "#ef4444",
    "capacitor": "#3b82f6",
    "resistor": "#22c55e",
    "connector": "#f59e0b",
    "inductor": "#a855f7",
    "crystal": "#14b8a6",
    "header": "#f97316",
    "test_point": "#ec4899",
    "unknown": "#6b7280",
}

_NET_COLORS: dict[str, str] = {
    "power": "#ef4444",
    "ground": "#6b7280",
    "data": "#3b82f6",
    "clock": "#f59e0b",
    "signal": "#06b6d4",
    "debug": "#d946ef",
    "unknown": "#6b7280",
}

_ZONE_COLORS: dict[str, str] = {
    "cpu": "#06b6d4",
    "memory": "#8b5cf6",
    "power": "#f59e0b",
    "io": "#22c55e",
    "debug": "#ef4444",
    "network": "#3b82f6",
    "storage": "#14b8a6",
}

_SECURITY_KEYWORDS = {
    "JTAG": ("JTAG debug — full CPU access", "HIGH", "CWE-1191"),
    "SWD": ("SWD debug — ARM CoreSight", "HIGH", "CWE-1191"),
    "UART": ("UART/serial console", "MED", "CWE-1299"),
    "CONSOLE": ("Serial console — bootloader/shell", "MED", "CWE-1299"),
    "SPI": ("SPI bus — firmware extraction", "MED", "CWE-1191"),
}

_DEFAULT_COLOR = "#6b7280"
_FONT = "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace"
_FONT_SIZE = 10
_BOX_OPACITY = "0.25"
_STROKE_WIDTH = "1.5"

BOM_PANEL_W = 220
BOM_PANEL_PAD = 10
BOM_LINE_H = 14

_TITLE_H = 32
_FOOTER_H = 24


def _color_for(label: str) -> str:
    return _LABEL_COLORS.get(label, _DEFAULT_COLOR)


def _escape(text: str) -> str:
    return html.escape(str(text))


def _classify_net(trace: Trace, comp_map: dict[str, Component]) -> str:
    from_c = comp_map.get(trace.from_component)
    to_c = comp_map.get(trace.to_component)

    from_label = from_c.label if from_c else ""
    to_label = to_c.label if to_c else ""
    from_marking = (from_c.marking if from_c else "").upper()
    to_marking = (to_c.marking if to_c else "").upper()
    all_text = f"{from_marking} {to_marking} {from_label} {to_label}"

    if any(kw in all_text for kw in ("JTAG", "SWD", "UART", "TDI", "TDO", "TCK", "TMS")):
        return "debug"
    if any(kw in all_text for kw in ("VRM", "TPS", "IR35", "VCC", "VDD", "PWR", "POWER")):
        return "power"
    if trace.width_px >= 5:
        return "power"
    if trace.width_px >= 4 and any(kw in all_text for kw in ("INDUCTOR", "inductor")):
        return "power"
    if any(kw in all_text for kw in ("CLK", "CLOCK", "MHZ", "OSC", "crystal", "CRYSTAL")):
        return "clock"
    if any(kw in all_text for kw in ("DDR", "RAM", "GDDR", "DATA", "SDIO", "SPI", "EMMC")):
        return "data"
    if any(kw in all_text for kw in ("GND", "VSS", "GROUND")):
        return "ground"
    return "signal"


def _center_of(comp: Component) -> tuple[int, int]:
    x, y, w, h = comp.bbox
    return x + w // 2, y + h // 2


def _edge_point(comp: Component, target_x: int, target_y: int) -> tuple[int, int]:
    x, y, w, h = comp.bbox
    cx, cy = x + w // 2, y + h // 2
    dx = target_x - cx
    dy = target_y - cy

    if abs(dx) < 1 and abs(dy) < 1:
        return cx, y

    if w > 0 and h > 0:
        scale_x = abs((w / 2) / dx) if abs(dx) > 0.01 else 1e6
        scale_y = abs((h / 2) / dy) if abs(dy) > 0.01 else 1e6
        scale = min(scale_x, scale_y)
        ex = int(cx + dx * scale)
        ey = int(cy + dy * scale)
        ex = max(x, min(x + w, ex))
        ey = max(y, min(y + h, ey))
        return ex, ey

    return cx, cy


def _is_security_component(comp: Component) -> bool:
    marking = (comp.marking or "").upper()
    label = (comp.label or "").lower()
    return any(kw in marking for kw in _SECURITY_KEYWORDS) or label in ("test_point",)


# ── SVG defs: filters, patterns, markers ──────────────────────────────

def _render_defs() -> str:
    return """  <defs>
    <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="10" cy="10" r="0.8" fill="#1a2a40"/>
    </pattern>
    <filter id="glow-red" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
      <feColorMatrix in="blur" type="matrix"
        values="1 0 0 0 0  0 0.2 0 0 0  0 0 0.2 0 0  0 0 0 0.6 0" result="red"/>
      <feMerge><feMergeNode in="red"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="glow-purple" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
      <feColorMatrix in="blur" type="matrix"
        values="0.8 0 0 0 0  0 0.2 0 0 0  0 0 1 0 0  0 0 0 0.5 0" result="p"/>
      <feMerge><feMergeNode in="p"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="panel-shadow" x="-5%" y="-5%" width="110%" height="110%">
      <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#000" flood-opacity="0.5"/>
    </filter>
    <marker id="arrow" viewBox="0 0 10 6" refX="9" refY="3"
            markerWidth="8" markerHeight="5" orient="auto-start-reverse">
      <path d="M 0 0 L 10 3 L 0 6 z" fill="context-stroke" fill-opacity="0.7"/>
    </marker>
  </defs>"""


# ── Background ────────────────────────────────────────────────────────

def _render_background(svg_w: int, svg_h: int) -> str:
    # Board margin for the PCB outline inset
    margin = 6
    bx = margin
    by = _TITLE_H + margin
    bw = svg_w - margin * 2
    bh = svg_h - _TITLE_H - _FOOTER_H - margin * 2

    parts: list[str] = []
    # Base fill
    parts.append(f'  <rect width="{svg_w}" height="{svg_h}" fill="{_BG}"/>')
    # Grid dot pattern over the whole canvas
    parts.append(f'  <rect width="{svg_w}" height="{svg_h}" fill="url(#grid)"/>')

    # PCB soldermask board rectangle (slightly lighter than background)
    parts.append(
        f'  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" '
        f'rx="4" ry="4" fill="#0b1120" fill-opacity="0.55" '
        f'stroke="#1e2d40" stroke-width="1.5"/>'
    )

    # Subtle copper-plane grid lines (horizontal + vertical, spaced 40px)
    copper_color = "#1a3050"
    copper_opacity = "0.35"
    grid_step = 40
    # Horizontal lines
    y_line = by + grid_step
    while y_line < by + bh:
        parts.append(
            f'  <line x1="{bx}" y1="{y_line}" x2="{bx + bw}" y2="{y_line}" '
            f'stroke="{copper_color}" stroke-width="0.5" stroke-opacity="{copper_opacity}"/>'
        )
        y_line += grid_step
    # Vertical lines
    x_line = bx + grid_step
    while x_line < bx + bw:
        parts.append(
            f'  <line x1="{x_line}" y1="{by}" x2="{x_line}" y2="{by + bh}" '
            f'stroke="{copper_color}" stroke-width="0.5" stroke-opacity="{copper_opacity}"/>'
        )
        x_line += grid_step

    # PCB board outline (beveled look: outer stroke + inner highlight)
    parts.append(
        f'  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" '
        f'rx="4" ry="4" fill="none" '
        f'stroke="#2a4060" stroke-width="2.5"/>'
    )
    # Inner highlight line (top-left edges only, simulating bevel)
    parts.append(
        f'  <path d="M{bx + 4},{by + bh - 4} L{bx + 4},{by + 4} L{bx + bw - 4},{by + 4}" '
        f'fill="none" stroke="#2e5070" stroke-width="0.8" stroke-opacity="0.5" '
        f'stroke-linecap="round"/>'
    )

    return "\n".join(parts)


# ── Title bar ─────────────────────────────────────────────────────────

def _render_title_bar(svg_w: int, title: str, result: AnalysisResult) -> str:
    total = len(result.components)
    n_traces = len(result.traces)
    identified = sum(1 for c in result.components if c.part_number)

    left_text = title or "re:trace analysis"
    right_text = f"{total} components · {identified} ID'd · {n_traces} traces"

    parts: list[str] = []
    parts.append('  <g class="title-bar">')
    parts.append(
        f'    <rect width="{svg_w}" height="{_TITLE_H}" '
        f'fill="{_PANEL_BG}" fill-opacity="0.92"/>'
    )
    parts.append(
        f'    <line x1="0" y1="{_TITLE_H}" x2="{svg_w}" y2="{_TITLE_H}" '
        f'stroke="{_ACCENT}" stroke-width="1" stroke-opacity="0.4"/>'
    )
    parts.append(
        f'    <text x="12" y="21" font-family={_q(_FONT)} '
        f'font-size="13" fill="{_ACCENT}" font-weight="bold">'
        f're:trace</text>'
    )
    parts.append(
        f'    <text x="80" y="21" font-family={_q(_FONT)} '
        f'font-size="11" fill="{_TEXT_HI}">{_escape(left_text)}</text>'
    )
    parts.append(
        f'    <text x="{svg_w - 12}" y="21" text-anchor="end" '
        f'font-family={_q(_FONT)} font-size="9" fill="{_TEXT_LO}">'
        f'{_escape(right_text)}</text>'
    )
    parts.append('  </g>')
    return "\n".join(parts)


# ── Components ────────────────────────────────────────────────────────

def _render_component(comp: Component) -> str:
    x, y, w, h = comp.bbox
    color = _color_for(comp.label)
    label_text = comp.part_number or comp.marking or comp.label
    label_text = label_text[:20]
    is_sec = _is_security_component(comp)

    text_y = y - 4 if y > (_TITLE_H + 16) else y + h + 12
    filt = ' filter="url(#glow-red)"' if is_sec else ""

    parts: list[str] = []
    parts.append(
        f'    <g class="component" data-id="{_escape(comp.id)}" '
        f'data-label="{_escape(comp.label)}"{filt}>'
    )
    parts.append(
        f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="{color}" fill-opacity="{_BOX_OPACITY}" '
        f'stroke="{color}" stroke-width="{_STROKE_WIDTH}" rx="2"/>'
    )
    parts.append(
        f'      <text x="{x + 3}" y="{y + 10}" font-family={_q(_FONT)} '
        f'font-size="8" fill="{color}" fill-opacity="0.6">'
        f'{_escape(comp.id)}</text>'
    )
    parts.append(
        f'      <text x="{x + 2}" y="{text_y}" font-family={_q(_FONT)} '
        f'font-size="{_FONT_SIZE}" fill="{color}" font-weight="bold">'
        f'{_escape(label_text)}</text>'
    )
    if is_sec:
        parts.append(
            f'      <rect x="{x + w - 8}" y="{y + 1}" width="7" height="7" '
            f'rx="1" fill="#ef4444" fill-opacity="0.9"/>'
        )
        parts.append(
            f'      <text x="{x + w - 7}" y="{y + 7}" font-family={_q(_FONT)} '
            f'font-size="5" fill="#fff" font-weight="bold">!</text>'
        )
    parts.append('    </g>')
    return "\n".join(parts)


# ── Traces ────────────────────────────────────────────────────────────

def _render_trace(
    trace: Trace,
    net_type: str,
    comp_map: dict[str, Component],
) -> str:
    color = _NET_COLORS.get(net_type, _NET_COLORS["unknown"])
    width = max(1.0, trace.width_px * 0.6)
    opacity = "0.55" if net_type == "ground" else "0.85"
    is_debug = net_type == "debug"
    is_power = net_type == "power"

    filt = ""
    if is_debug:
        filt = ' filter="url(#glow-purple)"'
    elif is_power:
        filt = ' filter="url(#glow-red)"'

    dash = ' stroke-dasharray="6,3"' if is_debug else ""
    marker = ' marker-end="url(#arrow)"' if trace.from_component and trace.to_component else ""

    parts: list[str] = []
    parts.append(
        f'    <g class="trace" data-id="{_escape(trace.id)}" data-net="{net_type}"{filt}>'
    )

    if trace.points and len(trace.points) >= 2:
        pts_str = " ".join(f"{px},{py}" for px, py in trace.points)
        parts.append(
            f'      <polyline points="{pts_str}" '
            f'fill="none" stroke="{color}" stroke-width="{width:.1f}" '
            f'stroke-opacity="{opacity}" stroke-linecap="round" '
            f'stroke-linejoin="round"{dash}{marker}/>'
        )

        for px, py in (trace.points[0], trace.points[-1]):
            parts.append(
                f'      <circle cx="{px}" cy="{py}" r="3" '
                f'fill="{color}" fill-opacity="0.9" stroke="{_BG}" stroke-width="1"/>'
            )

        if trace.from_component and trace.to_component and len(trace.points) >= 2:
            mid_idx = len(trace.points) // 2
            mx, my = trace.points[mid_idx]
            parts.append(
                f'      <text x="{mx}" y="{my - 5}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="7" fill="{color}" '
                f'fill-opacity="0.6">{net_type.upper()}</text>'
            )

    elif trace.from_component and trace.to_component:
        from_c = comp_map.get(trace.from_component)
        to_c = comp_map.get(trace.to_component)
        if from_c and to_c:
            tc = _center_of(to_c)
            fc = _center_of(from_c)
            p1 = _edge_point(from_c, tc[0], tc[1])
            p2 = _edge_point(to_c, fc[0], fc[1])
            parts.append(
                f'      <line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" '
                f'stroke="{color}" stroke-width="{width:.1f}" '
                f'stroke-opacity="{opacity}" stroke-linecap="round"{dash}{marker}/>'
            )
            for px, py in (p1, p2):
                parts.append(
                    f'      <circle cx="{px}" cy="{py}" r="3" '
                    f'fill="{color}" fill-opacity="0.9" stroke="{_BG}" stroke-width="1"/>'
                )

    parts.append('    </g>')
    return "\n".join(parts)


# ── BOM panel ─────────────────────────────────────────────────────────

def _render_bom_panel(result: AnalysisResult, svg_w: int, svg_h: int) -> str:
    counts: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    for c in result.components:
        counts[c.label] += 1
        if c.part_number:
            id_counts[c.label] += 1

    sorted_types = sorted(counts.items(), key=lambda kv: -kv[1])
    n_rows = len(sorted_types) + 3

    panel_h = BOM_PANEL_PAD * 2 + n_rows * BOM_LINE_H + 8
    panel_x = max(12, svg_w - BOM_PANEL_W - 12)
    panel_y = _TITLE_H + 10

    total = len(result.components)
    identified = sum(1 for c in result.components if c.part_number)
    n_traces = len(result.traces)
    connected = sum(1 for t in result.traces if t.from_component and t.to_component)

    parts: list[str] = []
    parts.append('    <g class="bom-panel" filter="url(#panel-shadow)">')
    parts.append(
        f'      <rect x="{panel_x}" y="{panel_y}" '
        f'width="{BOM_PANEL_W}" height="{panel_h}" '
        f'rx="6" fill="{_PANEL_BG}" fill-opacity="0.92" '
        f'stroke="{_PANEL_BORDER}" stroke-width="1"/>'
    )

    tx = panel_x + BOM_PANEL_PAD
    ty = panel_y + BOM_PANEL_PAD + 12

    parts.append(
        f'      <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
        f'font-size="11" fill="{_ACCENT}" font-weight="bold">Bill of Materials</text>'
    )
    ty += BOM_LINE_H + 2

    parts.append(
        f'      <line x1="{tx}" y1="{ty - 8}" '
        f'x2="{panel_x + BOM_PANEL_W - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="{_DIVIDER}" stroke-width="0.5"/>'
    )

    for label, count in sorted_types:
        color = _color_for(label)
        id_n = id_counts.get(label, 0)
        id_str = f"  ({id_n} ID'd)" if id_n else ""
        parts.append(
            f'      <rect x="{tx}" y="{ty - 8}" width="8" height="8" '
            f'fill="{color}" rx="2"/>'
        )
        parts.append(
            f'      <text x="{tx + 12}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="9" fill="{_TEXT_MID}">{_escape(label)}: {count}{id_str}</text>'
        )
        ty += BOM_LINE_H

    ty += 4
    parts.append(
        f'      <line x1="{tx}" y1="{ty - 8}" '
        f'x2="{panel_x + BOM_PANEL_W - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="{_DIVIDER}" stroke-width="0.5"/>'
    )
    parts.append(
        f'      <text x="{tx}" y="{ty + 2}" font-family={_q(_FONT)} '
        f'font-size="9" fill="{_TEXT_LO}">{total} parts, {identified} ID\'d, '
        f'{n_traces} traces, {connected} nets</text>'
    )

    parts.append('    </g>')
    return "\n".join(parts)


# ── Security panel ────────────────────────────────────────────────────

def _detect_security_findings(
    result: AnalysisResult,
) -> list[tuple[str, str, str, Component]]:
    findings: list[tuple[str, str, str, Component]] = []
    for comp in result.components:
        marking = (comp.marking or "").upper()
        for kw, (desc, sev, cwe) in _SECURITY_KEYWORDS.items():
            if kw in marking:
                findings.append((desc, sev, cwe, comp))
                break
    return findings


def _render_zones(
    zones: list[tuple[str, str, list[str]]],
    comp_map: dict[str, Component],
) -> str:
    """Render functional zone overlays from (name, zone_type, [component_ids])."""
    if not zones:
        return ""

    parts: list[str] = []
    parts.append('  <g class="zones">')

    for name, zone_type, comp_ids in zones:
        members = [comp_map[cid] for cid in comp_ids if cid in comp_map]
        if not members:
            continue

        pad = 18
        min_x = min(c.bbox[0] for c in members) - pad
        min_y = min(c.bbox[1] for c in members) - pad
        max_x = max(c.bbox[0] + c.bbox[2] for c in members) + pad
        max_y = max(c.bbox[1] + c.bbox[3] for c in members) + pad

        color = _ZONE_COLORS.get(zone_type, "#6b7280")
        w = max_x - min_x
        h = max_y - min_y

        parts.append(
            f'    <g class="zone" data-zone="{_escape(zone_type)}">'
        )
        parts.append(
            f'      <rect x="{min_x}" y="{min_y}" width="{w}" height="{h}" '
            f'rx="8" fill="{color}" fill-opacity="0.06" '
            f'stroke="{color}" stroke-width="1" stroke-opacity="0.3" '
            f'stroke-dasharray="6,4"/>'
        )
        parts.append(
            f'      <text x="{min_x + 4}" y="{min_y - 4}" '
            f'font-family={_q(_FONT)} font-size="8" fill="{color}" '
            f'fill-opacity="0.5" font-weight="bold">'
            f'{_escape(name.upper())}</text>'
        )
        parts.append('    </g>')

    parts.append('  </g>')
    return "\n".join(parts)


def _render_security_panel(
    findings: list[tuple[str, str, str, Component]],
    svg_w: int,
    svg_h: int,
) -> str:
    if not findings:
        return ""

    panel_w = 260
    line_h = 16
    panel_h = BOM_PANEL_PAD * 2 + (len(findings) + 1) * line_h + 12
    panel_x = 8
    panel_y = svg_h - _FOOTER_H - panel_h - 8

    parts: list[str] = []
    parts.append('  <g class="security-panel" filter="url(#panel-shadow)">')
    parts.append(
        f'    <rect x="{panel_x}" y="{panel_y}" width="{panel_w}" '
        f'height="{panel_h}" rx="6" fill="{_PANEL_BG}" fill-opacity="0.92" '
        f'stroke="#7f1d1d" stroke-width="1"/>'
    )

    tx = panel_x + BOM_PANEL_PAD
    ty = panel_y + BOM_PANEL_PAD + 12

    parts.append(
        f'    <rect x="{tx}" y="{ty - 10}" width="8" height="8" rx="2" fill="#ef4444"/>'
    )
    parts.append(
        f'    <text x="{tx + 12}" y="{ty - 2}" font-family={_q(_FONT)} '
        f'font-size="11" fill="#ef4444" font-weight="bold">Security Findings</text>'
    )
    ty += line_h + 2
    parts.append(
        f'    <line x1="{tx}" y1="{ty - 8}" x2="{panel_x + panel_w - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="#7f1d1d" stroke-width="0.5"/>'
    )

    for desc, sev, cwe, comp in findings:
        sev_color = "#ef4444" if sev == "HIGH" else "#f59e0b"
        parts.append(
            f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="8" fill="{sev_color}" font-weight="bold">[{sev}]</text>'
        )
        parts.append(
            f'    <text x="{tx + 36}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="8" fill="{_TEXT_MID}">'
            f'{_escape(comp.id)} {_escape(desc)} ({cwe})</text>'
        )
        ty += line_h

    parts.append('  </g>')
    return "\n".join(parts)


# ── Legend ─────────────────────────────────────────────────────────────

def _render_legend(svg_w: int) -> str:
    n_labels = len(_LABEL_COLORS)
    n_nets = len(_NET_COLORS)
    total_rows = n_labels + n_nets + 2
    panel_h = total_rows * 14 + 24
    panel_w = 110

    parts: list[str] = []
    parts.append('  <g class="legend">')
    parts.append(
        f'    <rect x="6" y="{_TITLE_H + 6}" width="{panel_w}" height="{panel_h}" '
        f'rx="6" fill="{_PANEL_BG}" fill-opacity="0.85" '
        f'stroke="{_PANEL_BORDER}" stroke-width="0.5"/>'
    )

    lx = 14
    ly = _TITLE_H + 20
    for i, (lbl, color) in enumerate(_LABEL_COLORS.items()):
        row_y = ly + i * 14
        parts.append(
            f'    <rect x="{lx}" y="{row_y - 9}" width="10" height="10" '
            f'fill="{color}" fill-opacity="0.8" rx="2"/>'
        )
        parts.append(
            f'    <text x="{lx + 14}" y="{row_y}" '
            f'font-family={_q(_FONT)} font-size="8" fill="{_TEXT_MID}">{lbl}</text>'
        )

    net_start_y = ly + n_labels * 14 + 8
    parts.append(
        f'    <text x="{lx}" y="{net_start_y}" '
        f'font-family={_q(_FONT)} font-size="8" fill="{_TEXT_LO}" '
        f'font-weight="bold">nets:</text>'
    )
    for i, (net, color) in enumerate(_NET_COLORS.items()):
        row_y = net_start_y + 14 + i * 14
        parts.append(
            f'    <line x1="{lx}" y1="{row_y - 4}" x2="{lx + 10}" y2="{row_y - 4}" '
            f'stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
        )
        parts.append(
            f'    <text x="{lx + 14}" y="{row_y}" '
            f'font-family={_q(_FONT)} font-size="8" fill="{_TEXT_MID}">{net}</text>'
        )

    parts.append('  </g>')
    return "\n".join(parts)


# ── Footer ────────────────────────────────────────────────────────────

def _render_footer(svg_w: int, svg_h: int, result: AnalysisResult) -> str:
    total = len(result.components)
    identified = sum(1 for c in result.components if c.part_number)
    n_traces = len(result.traces)
    connected = sum(1 for t in result.traces if t.from_component and t.to_component)
    footer = (
        f"{total} components, {identified} identified, "
        f"{n_traces} traces, {connected} connections "
        f"— re:trace {result.pipeline_version}"
    )

    fy = svg_h - _FOOTER_H
    parts: list[str] = []
    parts.append('  <g class="footer">')
    parts.append(
        f'    <rect y="{fy}" width="{svg_w}" height="{_FOOTER_H}" '
        f'fill="{_PANEL_BG}" fill-opacity="0.92"/>'
    )
    parts.append(
        f'    <line x1="0" y1="{fy}" x2="{svg_w}" y2="{fy}" '
        f'stroke="{_ACCENT}" stroke-width="1" stroke-opacity="0.3"/>'
    )
    parts.append(
        f'    <text x="{svg_w // 2}" y="{fy + 16}" '
        f'text-anchor="middle" font-family={_q(_FONT)} font-size="9" '
        f'fill="{_TEXT_LO}">{_escape(footer)}</text>'
    )
    parts.append('  </g>')
    return "\n".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────

def _q(s: str) -> str:
    return f'"{s}"'


# ── Main entry point ──────────────────────────────────────────────────

def generate_svg(
    result: AnalysisResult,
    width: Optional[int] = None,
    height: Optional[int] = None,
    image_href: Optional[str] = None,
    show_traces: bool = True,
    show_bom: bool = True,
    title: str = "",
    zones: Optional[list[tuple[str, str, list[str]]]] = None,
) -> str:
    bw, bh = result.board_dimensions
    svg_w = width or bw or 800
    svg_h = height or bh or 600

    comp_map = {c.id: c for c in result.components}

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append('  <!-- re:trace SVG overlay — components, traces, BOM -->')

    lines.append(_render_defs())
    lines.append(_render_background(svg_w, svg_h))

    if image_href and not image_href.strip().lower().startswith("javascript:"):
        href_lower = image_href.strip().lower()
        # Embed local files as base64 so the SVG is self-contained (e.g. on GitHub)
        if not (
            href_lower.startswith("http://")
            or href_lower.startswith("https://")
            or href_lower.startswith("data:")
        ):
            import base64
            from pathlib import Path

            img_path = Path(image_href)
            if img_path.is_file():
                raw = img_path.read_bytes()
                b64 = base64.b64encode(raw).decode("ascii")
                # Detect mime type from extension; default to png
                suffix = img_path.suffix.lower().lstrip(".")
                mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                        "gif": "gif", "webp": "webp", "svg": "svg+xml"}.get(suffix, "png")
                image_href = f"data:image/{mime};base64,{b64}"
            else:
                # Local file doesn't exist — skip the image tag entirely
                image_href = None

        if image_href:
            lines.append(
                f'  <image href="{_escape(image_href)}" x="0" y="{_TITLE_H}" '
                f'width="{svg_w}" height="{svg_h - _TITLE_H - _FOOTER_H}" '
                f'preserveAspectRatio="xMidYMid meet" opacity="0.85"/>'
            )

    lines.append(_render_title_bar(svg_w, title, result))
    lines.append(_render_legend(svg_w))

    if zones:
        lines.append(_render_zones(zones, comp_map))

    if show_traces and result.traces:
        lines.append('  <g class="traces">')
        for trace in result.traces:
            net_type = _classify_net(trace, comp_map)
            lines.append(_render_trace(trace, net_type, comp_map))
        lines.append('  </g>')

    lines.append('  <g class="components">')
    for comp in result.components:
        lines.append(_render_component(comp))
    lines.append('  </g>')

    if show_bom and result.components:
        lines.append(_render_bom_panel(result, svg_w, svg_h))

    sec_findings = _detect_security_findings(result)
    if sec_findings:
        lines.append(_render_security_panel(sec_findings, svg_w, svg_h))

    lines.append(_render_footer(svg_w, svg_h, result))

    lines.append('</svg>')
    return "\n".join(lines)


# ── Attack Surface SVG ───────────────────────────────────────────────

def generate_attack_surface_svg(
    result: AnalysisResult,
    attack_paths: list[tuple[str, str, str]],  # (from_ref, to_ref, label)
    security_refs: list[str],  # component refs to highlight
    width: Optional[int] = None,
    height: Optional[int] = None,
    title: str = "",
) -> str:
    """Generate an attack-surface SVG highlighting security-critical components and attack paths."""
    bw, bh = result.board_dimensions
    svg_w = width or bw or 800
    svg_h = height or bh or 600

    comp_map = {c.id: c for c in result.components}
    security_set = set(security_refs)

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append('  <!-- re:trace SVG overlay — Attack Surface Analysis -->')

    lines.append(_render_defs())
    lines.append(_render_background(svg_w, svg_h))
    lines.append(_render_title_bar(svg_w, title or "re:trace — Attack Surface Analysis", result))

    # All components at 20% opacity (dimmed)
    lines.append('  <g class="components-dimmed" opacity="0.2">')
    for comp in result.components:
        if comp.id not in security_set:
            lines.append(_render_component(comp))
    lines.append('  </g>')

    # Security-critical components at full opacity with red glow
    lines.append('  <g class="components-security">')
    for comp in result.components:
        if comp.id in security_set:
            x, y, w, h = comp.bbox
            color = _color_for(comp.label)
            label_text = comp.part_number or comp.marking or comp.label
            label_text = label_text[:20]
            text_y = y - 4 if y > (_TITLE_H + 16) else y + h + 12

            lines.append(
                f'    <g class="component-security" data-id="{_escape(comp.id)}" '
                f'filter="url(#glow-red)">'
            )
            lines.append(
                f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'fill="#ef4444" fill-opacity="0.15" '
                f'stroke="#ef4444" stroke-width="2.5" rx="2"/>'
            )
            lines.append(
                f'      <text x="{x + 3}" y="{y + 10}" font-family={_q(_FONT)} '
                f'font-size="8" fill="#ef4444" fill-opacity="0.9">'
                f'{_escape(comp.id)}</text>'
            )
            lines.append(
                f'      <text x="{x + 2}" y="{text_y}" font-family={_q(_FONT)} '
                f'font-size="{_FONT_SIZE}" fill="{color}" font-weight="bold">'
                f'{_escape(label_text)}</text>'
            )
            lines.append('    </g>')
    lines.append('  </g>')

    # Attack path arrows
    lines.append('  <g class="attack-paths">')
    for from_ref, to_ref, label in attack_paths:
        from_c = comp_map.get(from_ref)
        to_c = comp_map.get(to_ref)
        if not from_c or not to_c:
            continue

        tc = _center_of(to_c)
        fc = _center_of(from_c)
        p1 = _edge_point(from_c, tc[0], tc[1])
        p2 = _edge_point(to_c, fc[0], fc[1])

        # Thick red arrow line
        lines.append(
            f'    <line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" '
            f'stroke="#ef4444" stroke-width="3" stroke-opacity="0.9" '
            f'stroke-linecap="round" marker-end="url(#arrow)"/>'
        )

        # Endpoint dots
        for px, py in (p1, p2):
            lines.append(
                f'    <circle cx="{px}" cy="{py}" r="4" '
                f'fill="#ef4444" fill-opacity="0.9" stroke="{_BG}" stroke-width="1"/>'
            )

        # Label at midpoint
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2
        lines.append(
            f'    <text x="{mx}" y="{my - 8}" text-anchor="middle" '
            f'font-family={_q(_FONT)} font-size="8" fill="#fca5a5" '
            f'font-weight="bold">{_escape(label)}</text>'
        )
    lines.append('  </g>')

    # Attack surface legend panel
    n_paths = len(attack_paths)
    n_sec = len(security_refs)
    legend_line_h = 16
    legend_h = BOM_PANEL_PAD * 2 + (n_paths + 3) * legend_line_h + 12
    legend_w = 280
    legend_x = 8
    legend_y = svg_h - _FOOTER_H - legend_h - 8

    lines.append('  <g class="attack-legend" filter="url(#panel-shadow)">')
    lines.append(
        f'    <rect x="{legend_x}" y="{legend_y}" width="{legend_w}" '
        f'height="{legend_h}" rx="6" fill="{_PANEL_BG}" fill-opacity="0.92" '
        f'stroke="#7f1d1d" stroke-width="1"/>'
    )

    tx = legend_x + BOM_PANEL_PAD
    ty = legend_y + BOM_PANEL_PAD + 12

    lines.append(
        f'    <rect x="{tx}" y="{ty - 10}" width="8" height="8" rx="2" fill="#ef4444"/>'
    )
    lines.append(
        f'    <text x="{tx + 12}" y="{ty - 2}" font-family={_q(_FONT)} '
        f'font-size="11" fill="#ef4444" font-weight="bold">Attack Surface</text>'
    )
    ty += legend_line_h + 2
    lines.append(
        f'    <line x1="{tx}" y1="{ty - 8}" x2="{legend_x + legend_w - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="#7f1d1d" stroke-width="0.5"/>'
    )

    lines.append(
        f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
        f'font-size="8" fill="{_TEXT_MID}">'
        f'{n_sec} critical components, {n_paths} attack paths</text>'
    )
    ty += legend_line_h + 2

    for i, (from_ref, to_ref, label) in enumerate(attack_paths):
        step_num = i + 1
        lines.append(
            f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="8" fill="#fca5a5" font-weight="bold">[{step_num}]</text>'
        )
        lines.append(
            f'    <text x="{tx + 22}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="8" fill="{_TEXT_MID}">'
            f'{_escape(from_ref)} → {_escape(to_ref)}: {_escape(label)}</text>'
        )
        ty += legend_line_h

    lines.append('  </g>')

    lines.append(_render_footer(svg_w, svg_h, result))

    lines.append('</svg>')
    return "\n".join(lines)


# ── Zones-Only SVG ───────────────────────────────────────────────────

def generate_zones_svg(
    result: AnalysisResult,
    zones: list[tuple[str, str, list[str]]],  # (name, zone_type, [comp_ids])
    width: Optional[int] = None,
    height: Optional[int] = None,
    title: str = "",
) -> str:
    """Generate a clean functional-zone SVG — zones only, no trace clutter."""
    bw, bh = result.board_dimensions
    svg_w = width or bw or 800
    svg_h = height or bh or 600

    comp_map = {c.id: c for c in result.components}

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append('  <!-- re:trace SVG overlay — Functional Zone Map -->')

    lines.append(_render_defs())
    lines.append(_render_background(svg_w, svg_h))
    lines.append(_render_title_bar(svg_w, title or "re:trace — Functional Zone Map", result))

    # Components at 15% opacity (very faint, just for context)
    lines.append('  <g class="components-faint" opacity="0.15">')
    for comp in result.components:
        lines.append(_render_component(comp))
    lines.append('  </g>')

    # Zone rectangles rendered prominently
    if zones:
        lines.append('  <g class="zones-prominent">')
        for name, zone_type, comp_ids in zones:
            members = [comp_map[cid] for cid in comp_ids if cid in comp_map]
            if not members:
                continue

            pad = 18
            min_x = min(c.bbox[0] for c in members) - pad
            min_y = min(c.bbox[1] for c in members) - pad
            max_x = max(c.bbox[0] + c.bbox[2] for c in members) + pad
            max_y = max(c.bbox[1] + c.bbox[3] for c in members) + pad

            color = _ZONE_COLORS.get(zone_type, "#6b7280")
            w = max_x - min_x
            h = max_y - min_y
            cx = min_x + w // 2
            cy = min_y + h // 2
            comp_count = len(members)

            lines.append(
                f'    <g class="zone" data-zone="{_escape(zone_type)}">'
            )
            # Zone fill — higher opacity, solid border
            lines.append(
                f'      <rect x="{min_x}" y="{min_y}" width="{w}" height="{h}" '
                f'rx="8" fill="{color}" fill-opacity="0.15" '
                f'stroke="{color}" stroke-width="1.5" stroke-opacity="0.6"/>'
            )
            # Zone name — larger font, centered
            lines.append(
                f'      <text x="{cx}" y="{cy - 2}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="12" fill="{color}" '
                f'fill-opacity="0.85" font-weight="bold">'
                f'{_escape(name.upper())}</text>'
            )
            # Component count under zone name
            lines.append(
                f'      <text x="{cx}" y="{cy + 12}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="9" fill="{color}" '
                f'fill-opacity="0.6">'
                f'{comp_count} component{"s" if comp_count != 1 else ""}</text>'
            )
            lines.append('    </g>')
        lines.append('  </g>')

    lines.append(_render_footer(svg_w, svg_h, result))

    lines.append('</svg>')
    return "\n".join(lines)


def save_svg(result: AnalysisResult, output_path: str, **kwargs) -> None:
    """Write SVG to a file."""
    from pathlib import Path

    svg = generate_svg(result, **kwargs)
    Path(output_path).write_text(svg, encoding="utf-8")


# ── Interactive Layered SVG (Google Maps-style) ─────────────────────

_LAYER_DEFS = [
    ("board-image", "Board Image", True),
    ("components", "Components", True),
    ("traces", "Traces", True),
    ("zones", "Zones", False),
    ("security", "Security", False),
    ("bom-panel", "BOM Panel", True),
    ("net-labels", "Net Labels", False),
    ("grid-ref", "Grid Reference", False),
]

_PRESET_DEFS = {
    "analysis": {
        "label": "Analysis",
        "layers": ["board-image", "components", "traces", "bom-panel"],
    },
    "attack": {
        "label": "Attack Surface",
        "layers": ["board-image", "security", "traces"],
    },
    "zones": {
        "label": "Zones",
        "layers": ["board-image", "zones", "components"],
    },
    "debug": {
        "label": "Debug",
        "layers": ["board-image", "security", "net-labels"],
    },
    "clean": {
        "label": "Clean Board",
        "layers": ["board-image"],
    },
    "all": {
        "label": "All Layers",
        "layers": [ld[0] for ld in _LAYER_DEFS],
    },
}


def _render_interactive_controls(svg_w: int) -> str:
    """Render floating layer control panel with preset buttons and layer toggles."""
    panel_w = 160
    panel_x = svg_w - panel_w - 12
    panel_y = _TITLE_H + 8

    preset_count = len(_PRESET_DEFS)
    layer_count = len(_LAYER_DEFS)
    btn_h = 22
    row_h = 20
    header_h = 28
    preset_section_h = header_h + preset_count * btn_h + 8
    layer_section_h = header_h + layer_count * row_h + 8
    panel_h = preset_section_h + layer_section_h + 16

    parts: list[str] = []
    parts.append(f'  <g id="layer-controls" class="controls">')
    parts.append(
        f'    <rect x="{panel_x}" y="{panel_y}" width="{panel_w}" '
        f'height="{panel_h}" rx="8" fill="{_PANEL_BG}" fill-opacity="0.95" '
        f'stroke="{_PANEL_BORDER}" stroke-width="1" filter="url(#panel-shadow)"/>'
    )

    tx = panel_x + 10
    ty = panel_y + 18

    parts.append(
        f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
        f'font-size="10" fill="{_ACCENT}" font-weight="bold">VIEW PRESETS</text>'
    )
    ty += 8

    for preset_id, preset in _PRESET_DEFS.items():
        ty += btn_h
        parts.append(
            f'    <g class="preset-btn" data-preset="{preset_id}" '
            f'onclick="setPreset(\'{preset_id}\')" style="cursor: pointer;">'
        )
        parts.append(
            f'      <rect x="{tx}" y="{ty - 14}" width="{panel_w - 20}" height="{btn_h - 4}" '
            f'rx="4" fill="{_PANEL_BORDER}" fill-opacity="0.6" class="preset-bg"/>'
        )
        parts.append(
            f'      <text x="{tx + 8}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="9" fill="{_TEXT_HI}">{_escape(preset["label"])}</text>'
        )
        parts.append('    </g>')

    ty += 16

    parts.append(
        f'    <line x1="{tx}" y1="{ty}" x2="{panel_x + panel_w - 10}" y2="{ty}" '
        f'stroke="{_PANEL_BORDER}" stroke-width="0.5"/>'
    )
    ty += 18

    parts.append(
        f'    <text x="{tx}" y="{ty}" font-family={_q(_FONT)} '
        f'font-size="10" fill="{_ACCENT}" font-weight="bold">LAYERS</text>'
    )
    ty += 4

    for layer_id, layer_label, default_on in _LAYER_DEFS:
        ty += row_h
        fill = _ACCENT if default_on else _PANEL_BORDER
        parts.append(
            f'    <g class="layer-toggle" data-layer="{layer_id}" '
            f'onclick="toggleLayer(\'{layer_id}\')" style="cursor: pointer;">'
        )
        parts.append(
            f'      <rect x="{tx}" y="{ty - 10}" width="12" height="12" rx="2" '
            f'fill="{fill}" fill-opacity="0.8" stroke="{_TEXT_LO}" '
            f'stroke-width="0.5" id="chk-{layer_id}"/>'
        )
        if default_on:
            parts.append(
                f'      <text x="{tx + 6}" y="{ty}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="9" fill="{_BG}" '
                f'font-weight="bold" id="tick-{layer_id}">✓</text>'
            )
        else:
            parts.append(
                f'      <text x="{tx + 6}" y="{ty}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="9" fill="{_BG}" '
                f'font-weight="bold" id="tick-{layer_id}" '
                f'style="display:none">✓</text>'
            )
        parts.append(
            f'      <text x="{tx + 18}" y="{ty}" font-family={_q(_FONT)} '
            f'font-size="9" fill="{_TEXT_MID}" id="lbl-{layer_id}">'
            f'{_escape(layer_label)}</text>'
        )
        parts.append('    </g>')

    parts.append('  </g>')
    return "\n".join(parts)


def _render_interactive_script() -> str:
    """JavaScript for layer toggling and preset switching."""
    presets_js = "{"
    for pid, pdef in _PRESET_DEFS.items():
        layers_str = ",".join(f'"{l}"' for l in pdef["layers"])
        presets_js += f'"{pid}":[{layers_str}],'
    presets_js += "}"

    all_layers_js = ",".join(f'"{ld[0]}"' for ld in _LAYER_DEFS)

    return f"""  <script type="text/javascript">
    // <![CDATA[
    var presets = {presets_js};
    var allLayers = [{all_layers_js}];

    function toggleLayer(id) {{
      var g = document.getElementById("layer-" + id);
      if (!g) return;
      var vis = g.getAttribute("visibility");
      var show = vis === "hidden";
      g.setAttribute("visibility", show ? "visible" : "hidden");
      var chk = document.getElementById("chk-" + id);
      var tick = document.getElementById("tick-" + id);
      if (chk) chk.setAttribute("fill", show ? "{_ACCENT}" : "{_PANEL_BORDER}");
      if (tick) tick.style.display = show ? "" : "none";
    }}

    function setPreset(name) {{
      var layers = presets[name] || [];
      allLayers.forEach(function(id) {{
        var g = document.getElementById("layer-" + id);
        if (!g) return;
        var show = layers.indexOf(id) >= 0;
        g.setAttribute("visibility", show ? "visible" : "hidden");
        var chk = document.getElementById("chk-" + id);
        var tick = document.getElementById("tick-" + id);
        if (chk) chk.setAttribute("fill", show ? "{_ACCENT}" : "{_PANEL_BORDER}");
        if (tick) tick.style.display = show ? "" : "none";
      }});
    }}
    // ]]>
  </script>"""


def _render_grid_reference(svg_w: int, svg_h: int, spacing: int = 50) -> str:
    """Render a coordinate grid overlay with labels."""
    parts: list[str] = []
    color = "#1a3050"
    label_color = _TEXT_LO

    y_start = _TITLE_H
    y_end = svg_h - _FOOTER_H

    for x in range(0, svg_w, spacing):
        parts.append(
            f'    <line x1="{x}" y1="{y_start}" x2="{x}" y2="{y_end}" '
            f'stroke="{color}" stroke-width="0.5" stroke-opacity="0.4"/>'
        )
        if x > 0 and x % (spacing * 2) == 0:
            parts.append(
                f'    <text x="{x}" y="{y_start + 10}" font-family={_q(_FONT)} '
                f'font-size="7" fill="{label_color}" fill-opacity="0.5">{x}</text>'
            )

    for y in range(y_start, y_end, spacing):
        parts.append(
            f'    <line x1="0" y1="{y}" x2="{svg_w}" y2="{y}" '
            f'stroke="{color}" stroke-width="0.5" stroke-opacity="0.4"/>'
        )
        if y > y_start and (y - y_start) % (spacing * 2) == 0:
            parts.append(
                f'    <text x="2" y="{y + 3}" font-family={_q(_FONT)} '
                f'font-size="7" fill="{label_color}" fill-opacity="0.5">{y}</text>'
            )

    return "\n".join(parts)


def _render_net_labels(
    traces: list[Trace],
    comp_map: dict[str, Component],
) -> str:
    """Render net-type labels at trace midpoints."""
    parts: list[str] = []
    for trace in traces:
        if not trace.points or len(trace.points) < 2:
            if not (trace.from_component and trace.to_component):
                continue
            from_c = comp_map.get(trace.from_component)
            to_c = comp_map.get(trace.to_component)
            if from_c and to_c:
                fc = _center_of(from_c)
                tc = _center_of(to_c)
                mx, my = (fc[0] + tc[0]) // 2, (fc[1] + tc[1]) // 2
            else:
                continue
        else:
            mid = len(trace.points) // 2
            mx, my = trace.points[mid]

        net_type = _classify_net(trace, comp_map)
        color = _NET_COLORS.get(net_type, _NET_COLORS["unknown"])

        parts.append(
            f'    <rect x="{mx - 18}" y="{my - 8}" width="36" height="12" '
            f'rx="3" fill="{_BG}" fill-opacity="0.8"/>'
        )
        parts.append(
            f'    <text x="{mx}" y="{my + 1}" text-anchor="middle" '
            f'font-family={_q(_FONT)} font-size="7" fill="{color}" '
            f'font-weight="bold">{net_type.upper()}</text>'
        )

    return "\n".join(parts)


def generate_interactive_svg(
    result: AnalysisResult,
    width: Optional[int] = None,
    height: Optional[int] = None,
    image_href: Optional[str] = None,
    title: str = "",
    zones: Optional[list[tuple[str, str, list[str]]]] = None,
    attack_paths: Optional[list[tuple[str, str, str]]] = None,
    security_refs: Optional[list[str]] = None,
) -> str:
    """Generate an interactive layered SVG with toggleable layers and view presets.

    Like Google Maps: one SVG, multiple layer toggles (Components, Traces, Zones,
    Security, BOM, Grid, Net Labels), and preset view buttons (Analysis, Attack
    Surface, Zones, Debug, Clean Board, All Layers).
    """
    bw, bh = result.board_dimensions
    svg_w = width or bw or 800
    svg_h = height or bh or 600
    comp_map = {c.id: c for c in result.components}
    security_set = set(security_refs or [])

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append('  <!-- re:trace interactive layered SVG — toggle layers like a map -->')

    lines.append(_render_defs())
    lines.append(_render_background(svg_w, svg_h))

    resolved_href = _resolve_image_href(image_href)

    lines.append(f'  <g id="layer-board-image" visibility="visible">')
    if resolved_href:
        lines.append(
            f'    <image href="{_escape(resolved_href)}" x="0" y="{_TITLE_H}" '
            f'width="{svg_w}" height="{svg_h - _TITLE_H - _FOOTER_H}" '
            f'preserveAspectRatio="xMidYMid meet" opacity="0.85"/>'
        )
    lines.append('  </g>')

    lines.append(f'  <g id="layer-grid-ref" visibility="hidden">')
    lines.append(_render_grid_reference(svg_w, svg_h))
    lines.append('  </g>')

    lines.append(f'  <g id="layer-zones" visibility="hidden">')
    if zones:
        lines.append(_render_zones(zones, comp_map))
    lines.append('  </g>')

    lines.append(f'  <g id="layer-traces" visibility="visible">')
    if result.traces:
        lines.append('    <g class="traces">')
        for trace in result.traces:
            net_type = _classify_net(trace, comp_map)
            lines.append(_render_trace(trace, net_type, comp_map))
        lines.append('    </g>')
    lines.append('  </g>')

    lines.append(f'  <g id="layer-components" visibility="visible">')
    lines.append('    <g class="components">')
    for comp in result.components:
        lines.append(_render_component(comp))
    lines.append('    </g>')
    lines.append('  </g>')

    lines.append(f'  <g id="layer-security" visibility="hidden">')
    if security_set:
        lines.append('    <g class="security-highlights">')
        for comp in result.components:
            if comp.id in security_set:
                x, y, w, h = comp.bbox
                lines.append(
                    f'      <rect x="{x - 4}" y="{y - 4}" '
                    f'width="{w + 8}" height="{h + 8}" '
                    f'rx="4" fill="#ef4444" fill-opacity="0.12" '
                    f'stroke="#ef4444" stroke-width="2.5" '
                    f'filter="url(#glow-red)"/>'
                )
        lines.append('    </g>')
    if attack_paths:
        lines.append('    <g class="attack-paths">')
        for from_ref, to_ref, label in attack_paths:
            from_c = comp_map.get(from_ref)
            to_c = comp_map.get(to_ref)
            if not from_c or not to_c:
                continue
            tc = _center_of(to_c)
            fc = _center_of(from_c)
            p1 = _edge_point(from_c, tc[0], tc[1])
            p2 = _edge_point(to_c, fc[0], fc[1])
            lines.append(
                f'      <line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" '
                f'stroke="#ef4444" stroke-width="3" stroke-opacity="0.9" '
                f'stroke-linecap="round" marker-end="url(#arrow)"/>'
            )
            for px, py in (p1, p2):
                lines.append(
                    f'      <circle cx="{px}" cy="{py}" r="4" '
                    f'fill="#ef4444" fill-opacity="0.9" stroke="{_BG}" stroke-width="1"/>'
                )
            mx = (p1[0] + p2[0]) // 2
            my = (p1[1] + p2[1]) // 2
            lines.append(
                f'      <text x="{mx}" y="{my - 8}" text-anchor="middle" '
                f'font-family={_q(_FONT)} font-size="8" fill="#fca5a5" '
                f'font-weight="bold">{_escape(label)}</text>'
            )
        lines.append('    </g>')
    sec_findings = _detect_security_findings(result)
    if sec_findings:
        lines.append(_render_security_panel(sec_findings, svg_w, svg_h))
    lines.append('  </g>')

    lines.append(f'  <g id="layer-net-labels" visibility="hidden">')
    if result.traces:
        lines.append(_render_net_labels(result.traces, comp_map))
    lines.append('  </g>')

    lines.append(f'  <g id="layer-bom-panel" visibility="visible">')
    if result.components:
        lines.append(_render_bom_panel(result, svg_w, svg_h))
    lines.append('  </g>')

    lines.append(_render_title_bar(svg_w, title or "re:trace — Interactive Analysis", result))
    lines.append(_render_legend(svg_w))
    lines.append(_render_footer(svg_w, svg_h, result))

    lines.append(_render_interactive_controls(svg_w))
    lines.append(_render_interactive_script())

    lines.append('</svg>')
    return "\n".join(lines)


def _resolve_image_href(image_href: Optional[str]) -> Optional[str]:
    """Resolve image href to base64 data URI if it's a local file."""
    if not image_href:
        return None
    if image_href.strip().lower().startswith("javascript:"):
        return None

    href_lower = image_href.strip().lower()
    if href_lower.startswith(("http://", "https://", "data:")):
        return image_href

    import base64
    from pathlib import Path

    img_path = Path(image_href)
    if not img_path.is_file():
        return None

    raw = img_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    suffix = img_path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "gif": "gif", "webp": "webp", "svg": "svg+xml"}.get(suffix, "png")
    return f"data:image/{mime};base64,{b64}"


def save_interactive_svg(result: AnalysisResult, output_path: str, **kwargs) -> None:
    """Write interactive layered SVG to a file."""
    from pathlib import Path

    svg = generate_interactive_svg(result, **kwargs)
    Path(output_path).write_text(svg, encoding="utf-8")
