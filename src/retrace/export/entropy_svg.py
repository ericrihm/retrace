"""SVG entropy heatmap for firmware memory maps.

Renders block-wise Shannon entropy as a visual heatmap with color-coded
regions, magic byte annotations, and classification labels. Produces
standalone SVG suitable for reports and documentation.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _esc

from retrace.analysis.firmware_triage import TriageResult

_CLASSIFICATION_COLORS = {
    "null/padding": "#1a1a2e",
    "code/data": "#16537e",
    "text/structured": "#2d6a4f",
    "compressed": "#b5651d",
    "encrypted/random": "#9b2226",
}

_CLASSIFICATION_TEXT_COLORS = {
    "null/padding": "#4a4a6a",
    "code/data": "#58a6ff",
    "text/structured": "#3fb950",
    "compressed": "#f0883e",
    "encrypted/random": "#f85149",
}


def generate_entropy_svg(
    result: TriageResult,
    width: int = 900,
    bar_height: int = 40,
) -> str:
    """Render firmware entropy map as an SVG heatmap."""
    if not result.entropy_map:
        return ""

    total_size = sum(b.size for b in result.entropy_map)
    if total_size == 0:
        return ""

    margin_top = 80
    margin_bottom = 120
    margin_left = 60
    margin_right = 30
    graph_width = width - margin_left - margin_right
    graph_height = 200
    svg_height = margin_top + graph_height + bar_height + margin_bottom + 60

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {svg_height}" '
        f'font-family="\'JetBrains Mono\',\'Fira Code\',\'Consolas\',monospace">'
    )

    # Background
    parts.append(f'<rect width="{width}" height="{svg_height}" fill="#0d1117" rx="6"/>')

    # Title
    parts.append(
        f'<text x="{width // 2}" y="30" text-anchor="middle" fill="#f0f6fc" '
        f'font-size="14" font-weight="bold">Firmware Entropy Map</text>'
    )
    parts.append(
        f'<text x="{width // 2}" y="50" text-anchor="middle" fill="#8b949e" '
        f'font-size="10">{_esc(result.file_path)} — {result.file_size:,} bytes — '
        f'SHA-256: {result.sha256[:16]}...</text>'
    )

    # Y-axis label
    parts.append(
        f'<text x="15" y="{margin_top + graph_height // 2}" text-anchor="middle" '
        f'fill="#8b949e" font-size="9" transform="rotate(-90,15,'
        f'{margin_top + graph_height // 2})">Entropy (bits/byte)</text>'
    )

    # Y-axis ticks
    for val in range(0, 9):
        y: float = margin_top + graph_height - (val / 8.0 * graph_height)
        parts.append(
            f'<text x="{margin_left - 5}" y="{y + 3}" text-anchor="end" '
            f'fill="#8b949e" font-size="8">{val}</text>'
        )
        if val > 0:
            parts.append(
                f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + graph_width}" '
                f'y2="{y}" stroke="#21262d" stroke-width="0.5"/>'
            )

    # Threshold lines
    thresholds = [
        (1.0, "null", "#4a4a6a"),
        (4.0, "code", "#58a6ff"),
        (6.0, "text", "#3fb950"),
        (7.5, "compressed", "#f0883e"),
    ]
    for thresh_val, label, color in thresholds:
        ty = margin_top + graph_height - (thresh_val / 8.0 * graph_height)
        parts.append(
            f'<line x1="{margin_left}" y1="{ty}" x2="{margin_left + graph_width}" '
            f'y2="{ty}" stroke="{color}" stroke-width="0.5" stroke-dasharray="4,4" '
            f'opacity="0.5"/>'
        )

    # Entropy bars + graph points
    running_offset = 0
    points: list[str] = []
    for block in result.entropy_map:
        frac_start = running_offset / total_size
        frac_width = block.size / total_size
        bx = margin_left + frac_start * graph_width
        bw = max(1, frac_width * graph_width)

        # Graph point
        gy = margin_top + graph_height - (block.entropy / 8.0 * graph_height)
        gx = bx + bw / 2
        points.append(f"{gx},{gy}")

        # Filled bar under curve
        color = _CLASSIFICATION_COLORS.get(block.classification, "#333")
        parts.append(
            f'<rect x="{bx:.1f}" y="{gy:.1f}" width="{bw:.1f}" '
            f'height="{margin_top + graph_height - gy:.1f}" fill="{color}" opacity="0.6"/>'
        )

        running_offset += block.size

    # Line connecting points
    if len(points) > 1:
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" '
            f'stroke="#58a6ff" stroke-width="1.5" opacity="0.9"/>'
        )

    # Dots on points
    for pt in points:
        px, py = pt.split(",")
        parts.append(f'<circle cx="{px}" cy="{py}" r="2" fill="#58a6ff"/>')

    # Heatmap bar below graph
    bar_y = margin_top + graph_height + 15
    running_offset = 0
    for block in result.entropy_map:
        frac_start = running_offset / total_size
        frac_width = block.size / total_size
        bx = margin_left + frac_start * graph_width
        bw = max(1, frac_width * graph_width)
        color = _CLASSIFICATION_COLORS.get(block.classification, "#333")
        parts.append(
            f'<rect x="{bx:.1f}" y="{bar_y}" width="{bw:.1f}" height="{bar_height}" '
            f'fill="{color}" stroke="#0d1117" stroke-width="0.5"/>'
        )
        running_offset += block.size

    # Magic byte markers
    if result.magic_matches:
        marker_y = bar_y - 5
        for match in result.magic_matches[:15]:
            frac = match.offset / total_size if total_size > 0 else 0
            mx = margin_left + frac * graph_width
            parts.append(
                f'<line x1="{mx:.1f}" y1="{marker_y}" x2="{mx:.1f}" '
                f'y2="{bar_y + bar_height + 2}" stroke="#f0f6fc" stroke-width="1" '
                f'opacity="0.7"/>'
            )
            parts.append(
                f'<text x="{mx:.1f}" y="{bar_y + bar_height + 14}" text-anchor="middle" '
                f'fill="#f0f6fc" font-size="7" transform="rotate(45,{mx:.1f},'
                f'{bar_y + bar_height + 14})">{_esc(match.signature)}</text>'
            )

    # Legend
    legend_y = bar_y + bar_height + 50
    legend_items = [
        ("null/padding", "Null / Padding"),
        ("code/data", "Code / Data"),
        ("text/structured", "Text / Structured"),
        ("compressed", "Compressed"),
        ("encrypted/random", "Encrypted / Random"),
    ]
    lx = margin_left
    for cls, label in legend_items:
        color = _CLASSIFICATION_COLORS[cls]
        text_color = _CLASSIFICATION_TEXT_COLORS[cls]
        parts.append(f'<rect x="{lx}" y="{legend_y}" width="10" height="10" fill="{color}" rx="2"/>')
        parts.append(
            f'<text x="{lx + 14}" y="{legend_y + 9}" fill="{text_color}" font-size="8">'
            f'{_esc(label)}</text>'
        )
        lx += 130

    # X-axis label
    parts.append(
        f'<text x="{margin_left}" y="{bar_y + bar_height + 14}" fill="#8b949e" '
        f'font-size="8">0x00000000</text>'
    )
    parts.append(
        f'<text x="{margin_left + graph_width}" y="{bar_y + bar_height + 14}" '
        f'text-anchor="end" fill="#8b949e" font-size="8">'
        f'0x{total_size:08X}</text>'
    )

    # Overall stats
    stats_y = legend_y + 25
    parts.append(
        f'<text x="{margin_left}" y="{stats_y}" fill="#8b949e" font-size="8">'
        f'Overall entropy: {result.overall_entropy:.3f} bits/byte'
        f'{" | ENCRYPTED" if result.is_encrypted else ""}'
        f'{" | Bootloader detected" if result.has_bootloader else ""}'
        f'{" | Filesystem detected" if result.has_filesystem else ""}'
        f'</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)
