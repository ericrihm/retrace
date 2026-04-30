"""SVG annotated overlay export — bounding boxes and labels over the PCB image."""

from __future__ import annotations

import html
import textwrap
from typing import Optional

from retrace.core.pipeline import AnalysisResult, Component

# Colour palette per component label
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

_DEFAULT_COLOR = "#95a5a6"
_FONT_SIZE = 10
_BOX_OPACITY = "0.35"
_STROKE_WIDTH = "1.5"


def _color_for(label: str) -> str:
    return _LABEL_COLORS.get(label, _DEFAULT_COLOR)


def _escape(text: str) -> str:
    return html.escape(str(text))


def _render_component(comp: Component) -> str:
    x, y, w, h = comp.bbox
    color = _color_for(comp.label)
    label_text = comp.part_number or comp.marking or comp.label
    label_text = label_text[:20]  # truncate long strings

    # Clamp label above the box if close to top
    text_y = y - 3 if y > 14 else y + h + 12

    return textwrap.dedent(f"""\
        <g class="component" data-id="{_escape(comp.id)}" data-label="{_escape(comp.label)}">
          <rect x="{x}" y="{y}" width="{w}" height="{h}"
                fill="{color}" fill-opacity="{_BOX_OPACITY}"
                stroke="{color}" stroke-width="{_STROKE_WIDTH}" rx="2"/>
          <text x="{x + 2}" y="{text_y}"
                font-family="monospace" font-size="{_FONT_SIZE}"
                fill="{color}" font-weight="bold">{_escape(label_text)}</text>
        </g>""")


def generate_svg(
    result: AnalysisResult,
    width: Optional[int] = None,
    height: Optional[int] = None,
    image_href: Optional[str] = None,
) -> str:
    """Generate an SVG string with annotated component bounding boxes.

    The SVG is a standalone overlay sized to the board dimensions. When
    ``image_href`` is provided the PCB photo is embedded as a background
    ``<image>`` element so the SVG is self-contained.

    Args:
        result: Completed AnalysisResult from Pipeline.run().
        width:  Override SVG canvas width (pixels). Defaults to board width.
        height: Override SVG canvas height (pixels). Defaults to board height.
        image_href: Optional path or data-URI to embed as background image.

    Returns:
        UTF-8 SVG string.
    """
    bw, bh = result.board_dimensions
    svg_w = width or bw or 800
    svg_h = height or bh or 600

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append("  <!-- re:trace SVG overlay -->")

    # Optional background image
    if image_href:
        lines.append(
            f'  <image href="{_escape(image_href)}" x="0" y="0" '
            f'width="{svg_w}" height="{svg_h}" preserveAspectRatio="xMidYMid meet"/>'
        )

    # Legend
    legend_x = 8
    legend_y = 16
    lines.append('  <g class="legend">')
    for i, (lbl, color) in enumerate(_LABEL_COLORS.items()):
        ly = legend_y + i * 14
        lines.append(
            f'    <rect x="{legend_x}" y="{ly - 9}" width="10" height="10" '
            f'fill="{color}" fill-opacity="0.7" rx="1"/>'
        )
        lines.append(
            f'    <text x="{legend_x + 13}" y="{ly}" '
            f'font-family="monospace" font-size="9" fill="#ffffff">{lbl}</text>'
        )
    lines.append("  </g>")

    # Component annotations
    for comp in result.components:
        lines.append(_render_component(comp))

    # Summary footer
    total = len(result.components)
    identified = sum(1 for c in result.components if c.part_number)
    footer = f"{total} components, {identified} identified — re:trace {result.pipeline_version}"
    lines.append(
        f'  <text x="{svg_w // 2}" y="{svg_h - 4}" '
        f'text-anchor="middle" font-family="monospace" font-size="9" '
        f'fill="#aaaaaa">{_escape(footer)}</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


def save_svg(result: AnalysisResult, output_path: str, **kwargs) -> None:
    """Convenience wrapper — write SVG to a file.

    Args:
        result: Completed AnalysisResult.
        output_path: Destination file path (will be created/overwritten).
        **kwargs: Forwarded to :func:`generate_svg`.
    """
    from pathlib import Path

    svg = generate_svg(result, **kwargs)
    Path(output_path).write_text(svg, encoding="utf-8")
