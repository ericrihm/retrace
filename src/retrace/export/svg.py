"""SVG annotated overlay export — components, traces, BOM, and net topology."""

from __future__ import annotations

import html
from collections import Counter
from typing import Optional

from retrace.core.pipeline import AnalysisResult, Component, Trace

_LABEL_COLORS: dict[str, str] = {
    "ic": "#e74c3c",
    "capacitor": "#3498db",
    "resistor": "#2ecc71",
    "connector": "#f39c12",
    "inductor": "#9b59b6",
    "crystal": "#1abc9c",
    "header": "#e67e22",
    "test_point": "#e91e63",
    "unknown": "#95a5a6",
}

_NET_COLORS: dict[str, str] = {
    "power": "#ff3333",
    "ground": "#555555",
    "data": "#3399ff",
    "clock": "#ffaa00",
    "signal": "#66ccff",
    "debug": "#ff66ff",
    "unknown": "#888888",
}

_DEFAULT_COLOR = "#95a5a6"
_FONT = "monospace"
_FONT_SIZE = 10
_BOX_OPACITY = "0.35"
_STROKE_WIDTH = "1.5"

BOM_PANEL_W = 220
BOM_PANEL_PAD = 10
BOM_LINE_H = 14


def _color_for(label: str) -> str:
    return _LABEL_COLORS.get(label, _DEFAULT_COLOR)


def _escape(text: str) -> str:
    return html.escape(str(text))


def _classify_net(trace: Trace, comp_map: dict[str, Component]) -> str:
    """Classify a trace's net type from endpoint component context and trace width."""
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
    """Find the nearest edge point on a component's bbox toward a target point."""
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


def _render_component(comp: Component) -> str:
    x, y, w, h = comp.bbox
    color = _color_for(comp.label)
    label_text = comp.part_number or comp.marking or comp.label
    label_text = label_text[:20]

    text_y = y - 3 if y > 14 else y + h + 12

    return (
        f'    <g class="component" data-id="{_escape(comp.id)}" data-label="{_escape(comp.label)}">\n'
        f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="{color}" fill-opacity="{_BOX_OPACITY}" '
        f'stroke="{color}" stroke-width="{_STROKE_WIDTH}" rx="2"/>\n'
        f'      <text x="{x + 2}" y="{text_y}" '
        f'font-family="{_FONT}" font-size="{_FONT_SIZE}" '
        f'fill="{color}" font-weight="bold">{_escape(label_text)}</text>\n'
        f'    </g>'
    )


def _render_trace(
    trace: Trace,
    net_type: str,
    comp_map: dict[str, Component],
) -> str:
    """Render a trace as a polyline with pin dots and optional net label."""
    color = _NET_COLORS.get(net_type, _NET_COLORS["unknown"])
    width = max(1.0, trace.width_px * 0.6)
    opacity = "0.7" if net_type == "ground" else "0.85"

    parts: list[str] = []
    parts.append(f'    <g class="trace" data-id="{_escape(trace.id)}" data-net="{net_type}">')

    if trace.points and len(trace.points) >= 2:
        pts_str = " ".join(f"{px},{py}" for px, py in trace.points)
        parts.append(
            f'      <polyline points="{pts_str}" '
            f'fill="none" stroke="{color}" stroke-width="{width:.1f}" '
            f'stroke-opacity="{opacity}" stroke-linecap="round" stroke-linejoin="round"/>'
        )

        for px, py in (trace.points[0], trace.points[-1]):
            parts.append(
                f'      <circle cx="{px}" cy="{py}" r="3" '
                f'fill="{color}" fill-opacity="0.9" stroke="#fff" stroke-width="0.5"/>'
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
                f'stroke-opacity="{opacity}" stroke-linecap="round"/>'
            )
            for px, py in (p1, p2):
                parts.append(
                    f'      <circle cx="{px}" cy="{py}" r="3" '
                    f'fill="{color}" fill-opacity="0.9" stroke="#fff" stroke-width="0.5"/>'
                )

    parts.append('    </g>')
    return "\n".join(parts)


def _render_bom_panel(
    result: AnalysisResult,
    svg_w: int,
    svg_h: int,
) -> str:
    """Render a semi-transparent BOM summary panel in the top-right corner."""
    counts: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    for c in result.components:
        counts[c.label] += 1
        if c.part_number:
            id_counts[c.label] += 1

    sorted_types = sorted(counts.items(), key=lambda kv: -kv[1])
    n_rows = len(sorted_types) + 3  # header + divider + total

    panel_h = BOM_PANEL_PAD * 2 + n_rows * BOM_LINE_H + 8
    panel_x = svg_w - BOM_PANEL_W - 12
    panel_y = 12

    total = len(result.components)
    identified = sum(1 for c in result.components if c.part_number)
    n_traces = len(result.traces)
    connected = sum(1 for t in result.traces if t.from_component and t.to_component)

    parts: list[str] = []
    parts.append('    <g class="bom-panel">')
    parts.append(
        f'      <rect x="{panel_x}" y="{panel_y}" '
        f'width="{BOM_PANEL_W}" height="{panel_h}" '
        f'rx="4" fill="#1a1a2e" fill-opacity="0.88" stroke="#334" stroke-width="1"/>'
    )

    tx = panel_x + BOM_PANEL_PAD
    ty = panel_y + BOM_PANEL_PAD + 12

    parts.append(
        f'      <text x="{tx}" y="{ty}" font-family="{_FONT}" '
        f'font-size="11" fill="#e0e0e0" font-weight="bold">Bill of Materials</text>'
    )
    ty += BOM_LINE_H + 2

    parts.append(
        f'      <line x1="{tx}" y1="{ty - 8}" x2="{panel_x + BOM_PANEL_W - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="#444" stroke-width="0.5"/>'
    )

    for label, count in sorted_types:
        color = _color_for(label)
        id_n = id_counts.get(label, 0)
        id_str = f"  ({id_n} ID'd)" if id_n else ""
        parts.append(
            f'      <rect x="{tx}" y="{ty - 8}" width="8" height="8" '
            f'fill="{color}" rx="1"/>'
        )
        parts.append(
            f'      <text x="{tx + 12}" y="{ty}" font-family="{_FONT}" '
            f'font-size="9" fill="#ccc">{label}: {count}{id_str}</text>'
        )
        ty += BOM_LINE_H

    ty += 4
    parts.append(
        f'      <line x1="{tx}" y1="{ty - 8}" x2="{panel_x + BOM_PANEL_W - BOM_PANEL_PAD}" '
        f'y2="{ty - 8}" stroke="#444" stroke-width="0.5"/>'
    )
    parts.append(
        f'      <text x="{tx}" y="{ty + 2}" font-family="{_FONT}" '
        f'font-size="9" fill="#aaa">{total} parts, {identified} ID\'d, '
        f'{n_traces} traces, {connected} nets</text>'
    )

    parts.append('    </g>')
    return "\n".join(parts)


def _render_legend(svg_w: int) -> str:
    """Render component type legend and net type legend."""
    parts: list[str] = []
    parts.append('  <g class="legend">')

    lx = 8
    ly = 16
    for i, (lbl, color) in enumerate(_LABEL_COLORS.items()):
        row_y = ly + i * 14
        parts.append(
            f'    <rect x="{lx}" y="{row_y - 9}" width="10" height="10" '
            f'fill="{color}" fill-opacity="0.7" rx="1"/>'
        )
        parts.append(
            f'    <text x="{lx + 13}" y="{row_y}" '
            f'font-family="{_FONT}" font-size="9" fill="#ffffff">{lbl}</text>'
        )

    net_start_y = ly + len(_LABEL_COLORS) * 14 + 10
    parts.append(
        f'    <text x="{lx}" y="{net_start_y}" '
        f'font-family="{_FONT}" font-size="9" fill="#aaa" font-weight="bold">nets:</text>'
    )
    for i, (net, color) in enumerate(_NET_COLORS.items()):
        row_y = net_start_y + 14 + i * 14
        parts.append(
            f'    <line x1="{lx}" y1="{row_y - 4}" x2="{lx + 10}" y2="{row_y - 4}" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'    <text x="{lx + 13}" y="{row_y}" '
            f'font-family="{_FONT}" font-size="9" fill="#ffffff">{net}</text>'
        )

    parts.append('  </g>')
    return "\n".join(parts)


def generate_svg(
    result: AnalysisResult,
    width: Optional[int] = None,
    height: Optional[int] = None,
    image_href: Optional[str] = None,
    show_traces: bool = True,
    show_bom: bool = True,
) -> str:
    """Generate an SVG with component boxes, traced connections, and BOM panel.

    Args:
        result: Completed AnalysisResult from Pipeline.run().
        width:  Override SVG canvas width (pixels).
        height: Override SVG canvas height (pixels).
        image_href: Optional path or data-URI for background image.
        show_traces: Render traced connections between components.
        show_bom: Render the BOM summary panel.

    Returns:
        UTF-8 SVG string.
    """
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

    if image_href:
        lines.append(
            f'  <image href="{_escape(image_href)}" x="0" y="0" '
            f'width="{svg_w}" height="{svg_h}" preserveAspectRatio="xMidYMid meet"/>'
        )

    lines.append(_render_legend(svg_w))

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

    total = len(result.components)
    identified = sum(1 for c in result.components if c.part_number)
    n_traces = len(result.traces)
    connected = sum(1 for t in result.traces if t.from_component and t.to_component)
    footer = (
        f"{total} components, {identified} identified, "
        f"{n_traces} traces, {connected} connections "
        f"— re:trace {result.pipeline_version}"
    )
    lines.append(
        f'  <text x="{svg_w // 2}" y="{svg_h - 4}" '
        f'text-anchor="middle" font-family="{_FONT}" font-size="9" '
        f'fill="#aaaaaa">{_escape(footer)}</text>'
    )

    lines.append('</svg>')
    return "\n".join(lines)


def save_svg(result: AnalysisResult, output_path: str, **kwargs) -> None:
    """Write SVG to a file."""
    from pathlib import Path

    svg = generate_svg(result, **kwargs)
    Path(output_path).write_text(svg, encoding="utf-8")
