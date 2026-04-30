"""BOM (Bill of Materials) generator for retrace analysis results."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from retrace.core.pipeline import AnalysisResult, Component


def _component_to_bom_row(comp: Component) -> dict[str, Any]:
    return {
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

    fieldnames = ["id", "label", "part_number", "marking", "value", "package", "datasheet_url", "confidence"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in components:
        writer.writerow(row)
    return buf.getvalue()
