"""BOM (Bill of Materials) generator for retrace analysis results."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from retrace.core.pipeline import AnalysisResult, Component

# ── Dark-theme palette (matching svg.py) ────────────────────────────────

_BG = "#0a0e1a"
_PANEL_BG = "#111827"
_PANEL_BORDER = "#1e293b"
_TEXT_HI = "#e2e8f0"
_TEXT_MID = "#94a3b8"
_TEXT_LO = "#64748b"
_ACCENT = "#22d3ee"
_ROW_EVEN = "#0f1629"
_ROW_ODD = "#111d35"
_ROW_BORDER = "#1e293b"
_CONF_GREEN = "#22c55e"
_CONF_YELLOW = "#f59e0b"
_CONF_RED = "#ef4444"
_CONF_BG = "#1e293b"

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

_FONT = "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace"

# Sort priority for component grouping — lower number = earlier in table
_SORT_ORDER: dict[str, int] = {
    "ic": 0,
    "connector": 1,
    "capacitor": 2,
    "resistor": 3,
    "inductor": 4,
    "crystal": 5,
    "header": 6,
    "test_point": 7,
    "unknown": 99,
}

_HEADER_H = 32
_SUMMARY_H = 24
_COL_HEADER_H = 24
_ROW_H = 20
_GROUP_ROW_H = 22
_FOOTER_H = 24
_SVG_W = 900

# Column X-offsets and widths
_COL_REF_X = 16
_COL_TYPE_X = 100
_COL_PART_X = 200
_COL_MARK_X = 400
_COL_VAL_X = 540
_COL_PKG_X = 640
_COL_CONF_X = 740
_COL_CONF_BAR_W = 120


def _esc(text: str | None) -> str:
    """HTML-escape a value, treating None as empty string."""
    if text is None:
        return ""
    return html.escape(str(text))


def _conf_color(confidence: float) -> str:
    if confidence > 0.9:
        return _CONF_GREEN
    if confidence > 0.7:
        return _CONF_YELLOW
    return _CONF_RED


def _label_color(label: str) -> str:
    return _LABEL_COLORS.get(label, "#6b7280")


def _pretty_type(label: str) -> str:
    return label.replace("_", " ").title()


def _component_to_bom_row(comp: Component) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": comp.id,
        "label": comp.label,
        "part_number": comp.part_number,
        "marking": comp.marking,
        "value": comp.value,
        "package": comp.package,
        "datasheet_url": comp.datasheet_url,
        "confidence": round(comp.confidence, 4),
        "bbox": list(comp.bbox),
    }
    if comp.part_number:
        try:
            from retrace.identification.matcher import lookup_security_intel
            intel = lookup_security_intel(comp.part_number)
            if intel:
                row["security_intel"] = intel
                for k, v in intel.items():
                    row[f"intel_{k}"] = ", ".join(v) if isinstance(v, list) else str(v)
        except Exception:
            pass
    return row


def generate_bom(result: AnalysisResult) -> dict[str, Any]:
    """Produce a structured BOM dict from an AnalysisResult.

    The returned dict contains:
      - ``metadata``: image path, board dimensions, pipeline version, timestamp
      - ``components``: list of dicts with full component data
      - ``summary``: counts per label type and identification rate

    Args:
        result: Completed AnalysisResult from Pipeline.run().

    Returns:
        Structured BOM as a plain dict (JSON-serialisable).
    """
    components = [_component_to_bom_row(c) for c in result.components]

    by_label: dict[str, int] = {}
    for c in result.components:
        by_label[c.label] = by_label.get(c.label, 0) + 1

    identified = sum(1 for c in result.components if c.part_number)
    total = len(result.components)

    return {
        "metadata": {
            "image_path": result.image_path,
            "board_dimensions": list(result.board_dimensions),
            "pipeline_version": result.pipeline_version,
            "timestamp": result.timestamp,
            "duration_seconds": round(result.duration_seconds, 2),
        },
        "summary": {
            "total_components": total,
            "identified": identified,
            "unidentified": total - identified,
            "identification_rate": round(identified / total, 4) if total else 0.0,
            "by_label": by_label,
            "total_traces": len(result.traces),
        },
        "components": components,
    }


def bom_to_json(bom: dict[str, Any], indent: int = 2) -> str:
    """Serialize a BOM dict to a JSON string.

    Args:
        bom: Dict produced by :func:`generate_bom`.
        indent: JSON indentation level (default 2).

    Returns:
        Formatted JSON string.
    """
    return json.dumps(bom, indent=indent)


def bom_to_csv(bom: dict[str, Any]) -> str:
    """Serialize the components section of a BOM to CSV.

    Only the ``components`` list is serialised; metadata and summary are omitted.

    Args:
        bom: Dict produced by :func:`generate_bom`.

    Returns:
        CSV text with header row and one row per component.
    """
    components = bom.get("components", [])
    if not components:
        return "id,label,part_number,marking,value,package,datasheet_url,confidence\n"

    base_fields = ["id", "label", "part_number", "marking", "value", "package", "datasheet_url", "confidence"]
    intel_fields = sorted({k for row in components for k in row if k.startswith("intel_")})
    fieldnames = base_fields + intel_fields
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in components:
        writer.writerow(row)
    return buf.getvalue()


def bom_to_svg(bom: dict[str, Any], title: str = "", board_name: str = "") -> str:
    """Render a BOM dict as a dark-themed SVG table.

    Produces a self-contained SVG with no external references.  Components are
    grouped by type (ICs first, then connectors, passives, others) with coloured
    type indicators and confidence progress bars.

    Args:
        bom: Dict produced by :func:`generate_bom`.
        title: Optional explicit title (unused legacy param, kept for compat).
        board_name: Board name shown in the header bar.

    Returns:
        SVG markup as a string.
    """
    from retrace import __version__

    components = bom.get("components", [])
    summary = bom.get("summary", {})
    total = summary.get("total_components", len(components))
    identified = summary.get("identified", 0)
    rate = summary.get("identification_rate", 0.0)

    # ── Group and sort components ────────────────────────────────────
    groups: dict[str, list[dict[str, Any]]] = {}
    for comp in components:
        label = comp.get("label", "unknown")
        groups.setdefault(label, []).append(comp)

    sorted_labels = sorted(groups.keys(), key=lambda lb: (_SORT_ORDER.get(lb, 50), lb))

    # Count total rows (group headers + data rows)
    total_rows = 0
    for label in sorted_labels:
        total_rows += 1  # group header
        total_rows += len(groups[label])

    # ── Calculate SVG height ─────────────────────────────────────────
    content_h = sum(
        _GROUP_ROW_H + len(groups[label]) * _ROW_H for label in sorted_labels
    )
    svg_h = _HEADER_H + _SUMMARY_H + _COL_HEADER_H + content_h + _FOOTER_H

    lines: list[str] = []
    _a = lines.append

    # ── SVG root ─────────────────────────────────────────────────────
    _a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_W}" height="{svg_h}"'
       f' viewBox="0 0 {_SVG_W} {svg_h}" font-family="{_FONT}">')

    # Background
    _a(f'<rect width="{_SVG_W}" height="{svg_h}" fill="{_BG}"/>')

    # ── 1. Header bar (32px) ─────────────────────────────────────────
    _a(f'<rect x="0" y="0" width="{_SVG_W}" height="{_HEADER_H}" fill="{_PANEL_BG}"/>')
    _a(f'<line x1="0" y1="{_HEADER_H}" x2="{_SVG_W}" y2="{_HEADER_H}"'
       f' stroke="{_PANEL_BORDER}" stroke-width="1"/>')
    # Left: re:trace
    _a(f'<text x="16" y="22" fill="{_ACCENT}" font-size="14" font-weight="bold">'
       f're:trace</text>')
    # Center: board name
    _a(f'<text x="{_SVG_W // 2}" y="22" fill="{_TEXT_HI}" font-size="12"'
       f' text-anchor="middle">{_esc(board_name)}</text>')
    # Right: Bill of Materials
    _a(f'<text x="{_SVG_W - 16}" y="22" fill="{_TEXT_MID}" font-size="11"'
       f' text-anchor="end">Bill of Materials</text>')

    # ── 2. Summary strip (24px) ──────────────────────────────────────
    y_sum = _HEADER_H
    _a(f'<rect x="0" y="{y_sum}" width="{_SVG_W}" height="{_SUMMARY_H}"'
       f' fill="{_PANEL_BG}" opacity="0.8"/>')
    _a(f'<line x1="0" y1="{y_sum + _SUMMARY_H}" x2="{_SVG_W}"'
       f' y2="{y_sum + _SUMMARY_H}" stroke="{_PANEL_BORDER}" stroke-width="0.5"/>')
    sum_y_text = y_sum + 16
    _a(f'<text x="16" y="{sum_y_text}" fill="{_TEXT_MID}" font-size="10">'
       f'{total} components</text>')
    _a(f'<text x="160" y="{sum_y_text}" fill="{_TEXT_MID}" font-size="10">'
       f'{identified} identified</text>')
    rate_pct = f"{rate * 100:.1f}%"
    rate_color = _CONF_GREEN if rate > 0.9 else (_CONF_YELLOW if rate > 0.7 else _CONF_RED)
    _a(f'<text x="310" y="{sum_y_text}" fill="{rate_color}" font-size="10"'
       f' font-weight="bold">{rate_pct} identification rate</text>')

    # ── 3. Column headers (24px) ─────────────────────────────────────
    y_col = _HEADER_H + _SUMMARY_H
    _a(f'<rect x="0" y="{y_col}" width="{_SVG_W}" height="{_COL_HEADER_H}"'
       f' fill="{_PANEL_BG}"/>')
    col_y_text = y_col + 16
    for label_text, x_pos in [
        ("Ref", _COL_REF_X),
        ("Type", _COL_TYPE_X),
        ("Part Number", _COL_PART_X),
        ("Marking", _COL_MARK_X),
        ("Value", _COL_VAL_X),
        ("Package", _COL_PKG_X),
        ("Confidence", _COL_CONF_X),
    ]:
        _a(f'<text x="{x_pos}" y="{col_y_text}" fill="{_TEXT_HI}" font-size="10"'
           f' font-weight="bold">{label_text}</text>')
    # Cyan separator line below column headers
    sep_y = y_col + _COL_HEADER_H
    _a(f'<line x1="0" y1="{sep_y}" x2="{_SVG_W}" y2="{sep_y}"'
       f' stroke="{_ACCENT}" stroke-width="1" opacity="0.5"/>')

    # ── 4. Component rows ────────────────────────────────────────────
    y_cursor = _HEADER_H + _SUMMARY_H + _COL_HEADER_H
    row_index = 0  # for alternating backgrounds

    for label in sorted_labels:
        group_comps = groups[label]
        color = _label_color(label)
        pretty = _pretty_type(label)

        # Group header row
        _a(f'<rect x="0" y="{y_cursor}" width="{_SVG_W}" height="{_GROUP_ROW_H}"'
           f' fill="{_PANEL_BG}" opacity="0.6"/>')
        _a(f'<circle cx="24" cy="{y_cursor + _GROUP_ROW_H // 2}" r="4" fill="{color}"/>')
        _a(f'<text x="36" y="{y_cursor + 15}" fill="{color}" font-size="11"'
           f' font-weight="bold">{_esc(pretty)}</text>')
        _a(f'<text x="180" y="{y_cursor + 15}" fill="{_TEXT_LO}" font-size="10">'
           f'({len(group_comps)})</text>')
        y_cursor += _GROUP_ROW_H

        # Sort components within group by ref id
        group_comps_sorted = sorted(group_comps, key=lambda c: c.get("id", ""))

        for comp in group_comps_sorted:
            bg = _ROW_EVEN if row_index % 2 == 0 else _ROW_ODD
            _a(f'<rect x="0" y="{y_cursor}" width="{_SVG_W}" height="{_ROW_H}"'
               f' fill="{bg}"/>')
            # Subtle bottom border
            _a(f'<line x1="0" y1="{y_cursor + _ROW_H}" x2="{_SVG_W}"'
               f' y2="{y_cursor + _ROW_H}" stroke="{_ROW_BORDER}"'
               f' stroke-width="0.5"/>')

            text_y = y_cursor + 14

            # Ref
            _a(f'<text x="{_COL_REF_X}" y="{text_y}" fill="{_TEXT_HI}"'
               f' font-size="10">{_esc(comp.get("id", ""))}</text>')

            # Type dot
            _a(f'<circle cx="{_COL_TYPE_X + 4}" cy="{y_cursor + _ROW_H // 2}"'
               f' r="4" fill="{color}"/>')
            _a(f'<text x="{_COL_TYPE_X + 14}" y="{text_y}" fill="{_TEXT_MID}"'
               f' font-size="9">{_esc(comp.get("label", ""))}</text>')

            # Part number
            pn = comp.get("part_number", "")
            pn_color = _ACCENT if pn else _TEXT_LO
            pn_display = pn if pn else "—"
            _a(f'<text x="{_COL_PART_X}" y="{text_y}" fill="{pn_color}"'
               f' font-size="10">{_esc(pn_display)}</text>')

            # Marking
            marking = comp.get("marking", "") or ""
            _a(f'<text x="{_COL_MARK_X}" y="{text_y}" fill="{_TEXT_MID}"'
               f' font-size="10">{_esc(marking)}</text>')

            # Value
            value = comp.get("value", "") or ""
            _a(f'<text x="{_COL_VAL_X}" y="{text_y}" fill="{_TEXT_MID}"'
               f' font-size="10">{_esc(value)}</text>')

            # Package
            package = comp.get("package", "") or ""
            _a(f'<text x="{_COL_PKG_X}" y="{text_y}" fill="{_TEXT_MID}"'
               f' font-size="10">{_esc(package)}</text>')

            # Confidence bar
            conf = comp.get("confidence", 0.0)
            conf_color = _conf_color(conf)
            bar_y = y_cursor + 5
            bar_h = _ROW_H - 10
            bar_w = max(1, int(_COL_CONF_BAR_W * conf))
            # Background track
            _a(f'<rect x="{_COL_CONF_X}" y="{bar_y}" width="{_COL_CONF_BAR_W}"'
               f' height="{bar_h}" rx="2" fill="{_CONF_BG}"/>')
            # Filled portion
            _a(f'<rect x="{_COL_CONF_X}" y="{bar_y}" width="{bar_w}"'
               f' height="{bar_h}" rx="2" fill="{conf_color}" opacity="0.85"/>')
            # Percentage text on the bar
            conf_text_x = _COL_CONF_X + _COL_CONF_BAR_W + 6
            _a(f'<text x="{conf_text_x}" y="{text_y}" fill="{_TEXT_LO}"'
               f' font-size="9">{conf * 100:.0f}%</text>')

            y_cursor += _ROW_H
            row_index += 1

    # ── 5. Footer bar (24px) ─────────────────────────────────────────
    y_footer = y_cursor
    _a(f'<line x1="0" y1="{y_footer}" x2="{_SVG_W}" y2="{y_footer}"'
       f' stroke="{_PANEL_BORDER}" stroke-width="1"/>')
    _a(f'<rect x="0" y="{y_footer}" width="{_SVG_W}" height="{_FOOTER_H}"'
       f' fill="{_PANEL_BG}"/>')
    footer_text_y = y_footer + 16
    _a(f'<text x="16" y="{footer_text_y}" fill="{_TEXT_MID}" font-size="10">'
       f'{total} components · {identified} identified</text>')
    _a(f'<text x="{_SVG_W - 16}" y="{footer_text_y}" fill="{_TEXT_LO}"'
       f' font-size="10" text-anchor="end">re:trace v{_esc(__version__)}</text>')

    _a('</svg>')
    return "\n".join(lines)
