"""Tests for the BOM generator."""

from __future__ import annotations

import json


from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.bom import bom_to_csv, bom_to_json, generate_bom


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(n: int = 3) -> AnalysisResult:
    components = [
        Component(
            id=f"C{i:04d}",
            label="ic" if i % 2 == 0 else "resistor",
            confidence=0.9,
            bbox=(i * 10, i * 10, 20, 15),
            marking=f"MRK{i}",
            part_number="STM32F103" if i == 0 else "",
        )
        for i in range(n)
    ]
    return AnalysisResult(
        image_path="/test/board.jpg",
        components=components,
        traces=[Trace(id="T0001", points=[(0, 0), (10, 10)])],
        board_dimensions=(640, 480),
        pipeline_version="0.1.0",
        timestamp="2026-04-30T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_bom_structure():
    result = _make_result(3)
    bom = generate_bom(result)
    assert "metadata" in bom
    assert "summary" in bom
    assert "components" in bom


def test_generate_bom_component_count():
    result = _make_result(5)
    bom = generate_bom(result)
    assert bom["summary"]["total_components"] == 5
    assert len(bom["components"]) == 5


def test_generate_bom_identification_rate():
    result = _make_result(4)
    # Only component 0 has a part number
    bom = generate_bom(result)
    assert bom["summary"]["identified"] == 1
    assert bom["summary"]["unidentified"] == 3
    assert abs(bom["summary"]["identification_rate"] - 0.25) < 0.001


def test_bom_to_json_valid():
    result = _make_result(2)
    bom = generate_bom(result)
    json_str = bom_to_json(bom)
    parsed = json.loads(json_str)
    assert parsed["summary"]["total_components"] == 2


def test_bom_to_csv_has_header_and_rows():
    result = _make_result(3)
    bom = generate_bom(result)
    csv_str = bom_to_csv(bom)
    lines = csv_str.strip().splitlines()
    # Header + 3 data rows
    assert len(lines) == 4
    assert "part_number" in lines[0]


def test_bom_empty_result():
    result = AnalysisResult(image_path="x.jpg")
    bom = generate_bom(result)
    assert bom["summary"]["total_components"] == 0
    assert bom["summary"]["identification_rate"] == 0.0
    assert bom["components"] == []
