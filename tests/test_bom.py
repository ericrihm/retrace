"""Tests for src/retrace/export/bom.py — no ML dependencies."""

from __future__ import annotations

import csv
import io
import json
import re

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.bom import (
    bom_to_csv,
    bom_to_json,
    bom_to_svg,
    generate_bom,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_component(
    cid: str = "U0001",
    label: str = "ic",
    bbox: tuple[int, int, int, int] = (10, 20, 50, 40),
    confidence: float = 0.9,
    part_number: str = "",
    marking: str = "",
    value: str = "",
    package: str = "",
    datasheet_url: str = "",
) -> Component:
    return Component(
        id=cid,
        label=label,
        confidence=confidence,
        bbox=bbox,
        part_number=part_number,
        marking=marking,
        value=value,
        package=package,
        datasheet_url=datasheet_url,
    )


def _make_result(
    components: list[Component] | None = None,
    traces: list[Trace] | None = None,
    board_dimensions: tuple[int, int] = (640, 480),
    pipeline_version: str = "0.3.0",
    timestamp: str = "2026-04-30T00:00:00Z",
    duration_seconds: float = 1.23,
) -> AnalysisResult:
    return AnalysisResult(
        image_path="/test/board.jpg",
        components=components or [],
        traces=traces or [],
        board_dimensions=board_dimensions,
        pipeline_version=pipeline_version,
        timestamp=timestamp,
        duration_seconds=duration_seconds,
    )


def _make_trace(
    tid: str = "T00000001",
    points: list[tuple[int, int]] | None = None,
) -> Trace:
    return Trace(
        id=tid,
        points=points or [(0, 0), (100, 100)],
        width_px=2.0,
    )


# ---------------------------------------------------------------------------
# generate_bom — structure and metadata
# ---------------------------------------------------------------------------

class TestGenerateBomStructure:
    def test_returns_dict(self):
        result = _make_result()
        bom = generate_bom(result)
        assert isinstance(bom, dict)

    def test_top_level_keys(self):
        bom = generate_bom(_make_result())
        assert "metadata" in bom
        assert "summary" in bom
        assert "components" in bom

    def test_metadata_image_path(self):
        bom = generate_bom(_make_result())
        assert bom["metadata"]["image_path"] == "/test/board.jpg"

    def test_metadata_board_dimensions(self):
        bom = generate_bom(_make_result(board_dimensions=(1024, 768)))
        assert bom["metadata"]["board_dimensions"] == [1024, 768]

    def test_metadata_board_dimensions_is_list(self):
        bom = generate_bom(_make_result())
        assert isinstance(bom["metadata"]["board_dimensions"], list)

    def test_metadata_pipeline_version(self):
        bom = generate_bom(_make_result(pipeline_version="1.2.3"))
        assert bom["metadata"]["pipeline_version"] == "1.2.3"

    def test_metadata_timestamp(self):
        bom = generate_bom(_make_result(timestamp="2026-01-01T12:00:00Z"))
        assert bom["metadata"]["timestamp"] == "2026-01-01T12:00:00Z"

    def test_metadata_duration_rounded(self):
        bom = generate_bom(_make_result(duration_seconds=1.23456))
        assert bom["metadata"]["duration_seconds"] == 1.23

    def test_metadata_duration_two_decimals(self):
        bom = generate_bom(_make_result(duration_seconds=10.999))
        assert bom["metadata"]["duration_seconds"] == 11.0


# ---------------------------------------------------------------------------
# generate_bom — summary counts
# ---------------------------------------------------------------------------

class TestGenerateBomSummary:
    def test_total_components_zero_for_empty(self):
        bom = generate_bom(_make_result())
        assert bom["summary"]["total_components"] == 0

    def test_total_components_count(self):
        comps = [_make_component(f"U{i}") for i in range(5)]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["total_components"] == 5

    def test_identified_count_all_identified(self):
        comps = [_make_component(f"U{i}", part_number="LM317") for i in range(3)]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["identified"] == 3
        assert bom["summary"]["unidentified"] == 0

    def test_identified_count_none_identified(self):
        comps = [_make_component(f"U{i}", part_number="") for i in range(4)]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["identified"] == 0
        assert bom["summary"]["unidentified"] == 4

    def test_identified_count_partial(self):
        comps = [
            _make_component("U1", part_number="STM32"),
            _make_component("U2", part_number=""),
            _make_component("U3", part_number="NRF52"),
        ]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["identified"] == 2
        assert bom["summary"]["unidentified"] == 1

    def test_identification_rate_zero_for_empty(self):
        bom = generate_bom(_make_result())
        assert bom["summary"]["identification_rate"] == 0.0

    def test_identification_rate_one_hundred_percent(self):
        comps = [_make_component(f"C{i}", part_number="GRM155") for i in range(3)]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["identification_rate"] == 1.0

    def test_identification_rate_rounded_to_4dp(self):
        comps = [
            _make_component("U1", part_number="X"),
            _make_component("U2", part_number=""),
            _make_component("U3", part_number=""),
        ]
        bom = generate_bom(_make_result(components=comps))
        # 1/3 = 0.3333...
        assert bom["summary"]["identification_rate"] == round(1 / 3, 4)

    def test_by_label_counts(self):
        comps = [
            _make_component("U1", label="ic"),
            _make_component("U2", label="ic"),
            _make_component("C1", label="capacitor"),
            _make_component("R1", label="resistor"),
        ]
        bom = generate_bom(_make_result(components=comps))
        assert bom["summary"]["by_label"]["ic"] == 2
        assert bom["summary"]["by_label"]["capacitor"] == 1
        assert bom["summary"]["by_label"]["resistor"] == 1

    def test_by_label_empty_for_no_components(self):
        bom = generate_bom(_make_result())
        assert bom["summary"]["by_label"] == {}

    def test_total_traces_count(self):
        traces = [_make_trace(f"T{i:08d}") for i in range(7)]
        bom = generate_bom(_make_result(traces=traces))
        assert bom["summary"]["total_traces"] == 7

    def test_total_traces_zero_for_empty(self):
        bom = generate_bom(_make_result())
        assert bom["summary"]["total_traces"] == 0


# ---------------------------------------------------------------------------
# generate_bom — component rows
# ---------------------------------------------------------------------------

class TestGenerateBomComponents:
    def test_components_list_empty(self):
        bom = generate_bom(_make_result())
        assert bom["components"] == []

    def test_components_list_length_matches(self):
        comps = [_make_component(f"C{i}") for i in range(6)]
        bom = generate_bom(_make_result(components=comps))
        assert len(bom["components"]) == 6

    def test_component_row_keys(self):
        comp = _make_component("U1", part_number="LM317", marking="LM317T",
                               value="5V", package="TO-92",
                               datasheet_url="https://example.com/ds")
        bom = generate_bom(_make_result(components=[comp]))
        row = bom["components"][0]
        for key in ("id", "label", "part_number", "marking", "value",
                    "package", "datasheet_url", "confidence", "bbox"):
            assert key in row, f"Missing key: {key}"

    def test_component_id_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component("MY_REF")]))
        assert bom["components"][0]["id"] == "MY_REF"

    def test_component_label_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component(label="connector")]))
        assert bom["components"][0]["label"] == "connector"

    def test_component_part_number_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component(part_number="ATmega328P")]))
        assert bom["components"][0]["part_number"] == "ATmega328P"

    def test_component_marking_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component(marking="47R")]))
        assert bom["components"][0]["marking"] == "47R"

    def test_component_value_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component(value="100nF")]))
        assert bom["components"][0]["value"] == "100nF"

    def test_component_package_preserved(self):
        bom = generate_bom(_make_result(components=[_make_component(package="SOT-23")]))
        assert bom["components"][0]["package"] == "SOT-23"

    def test_component_datasheet_url_preserved(self):
        bom = generate_bom(_make_result(components=[
            _make_component(datasheet_url="https://example.com/ds.pdf")
        ]))
        assert bom["components"][0]["datasheet_url"] == "https://example.com/ds.pdf"

    def test_component_confidence_rounded_to_4dp(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.99999)]))
        assert bom["components"][0]["confidence"] == 1.0

    def test_component_confidence_low(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.12345)]))
        assert bom["components"][0]["confidence"] == 0.1235

    def test_component_bbox_is_list(self):
        bom = generate_bom(_make_result(components=[_make_component(bbox=(10, 20, 30, 40))]))
        assert bom["components"][0]["bbox"] == [10, 20, 30, 40]
        assert isinstance(bom["components"][0]["bbox"], list)

    def test_all_components_present_in_order(self):
        comps = [_make_component(f"R{i:03d}", label="resistor") for i in range(10)]
        bom = generate_bom(_make_result(components=comps))
        ids = [row["id"] for row in bom["components"]]
        assert ids == [f"R{i:03d}" for i in range(10)]

    def test_empty_string_fields_preserved(self):
        comp = _make_component("U1", part_number="", marking="", value="", package="")
        bom = generate_bom(_make_result(components=[comp]))
        row = bom["components"][0]
        assert row["part_number"] == ""
        assert row["marking"] == ""
        assert row["value"] == ""
        assert row["package"] == ""


# ---------------------------------------------------------------------------
# bom_to_json
# ---------------------------------------------------------------------------

class TestBomToJson:
    def test_returns_string(self):
        bom = generate_bom(_make_result())
        assert isinstance(bom_to_json(bom), str)

    def test_valid_json(self):
        bom = generate_bom(_make_result(components=[_make_component()]))
        result = json.loads(bom_to_json(bom))
        assert "metadata" in result

    def test_default_indent_is_2(self):
        bom = generate_bom(_make_result())
        output = bom_to_json(bom)
        # 2-space indent produces lines like "  "
        assert "  " in output
        assert "\t" not in output

    def test_custom_indent_zero(self):
        bom = generate_bom(_make_result())
        output = bom_to_json(bom, indent=0)
        parsed = json.loads(output)
        assert parsed["summary"]["total_components"] == 0

    def test_custom_indent_4(self):
        bom = generate_bom(_make_result())
        output = bom_to_json(bom, indent=4)
        # 4-space indent
        assert "    " in output

    def test_roundtrip_preserves_data(self):
        comps = [
            _make_component("U1", label="ic", part_number="LM317", confidence=0.95,
                            marking="317", value="5V", package="TO-92",
                            datasheet_url="https://example.com"),
        ]
        bom = generate_bom(_make_result(components=comps))
        parsed = json.loads(bom_to_json(bom))
        row = parsed["components"][0]
        assert row["id"] == "U1"
        assert row["part_number"] == "LM317"
        assert row["confidence"] == 0.95

    def test_empty_bom_serialisable(self):
        bom = generate_bom(_make_result())
        output = bom_to_json(bom)
        parsed = json.loads(output)
        assert parsed["components"] == []

    def test_json_contains_metadata(self):
        bom = generate_bom(_make_result(pipeline_version="9.9.9"))
        parsed = json.loads(bom_to_json(bom))
        assert parsed["metadata"]["pipeline_version"] == "9.9.9"

    def test_json_contains_summary(self):
        comps = [_make_component("U1", part_number="X")]
        bom = generate_bom(_make_result(components=comps))
        parsed = json.loads(bom_to_json(bom))
        assert parsed["summary"]["identified"] == 1


# ---------------------------------------------------------------------------
# bom_to_csv
# ---------------------------------------------------------------------------

class TestBomToCsv:
    def test_returns_string(self):
        bom = generate_bom(_make_result())
        assert isinstance(bom_to_csv(bom), str)

    def test_empty_bom_returns_header_only(self):
        bom = generate_bom(_make_result())
        csv_out = bom_to_csv(bom)
        assert csv_out == "id,label,part_number,marking,value,package,datasheet_url,confidence\n"

    def test_empty_components_key_returns_header(self):
        bom_no_key = {}
        csv_out = bom_to_csv(bom_no_key)
        assert "id" in csv_out
        assert "confidence" in csv_out

    def test_header_fields_present(self):
        bom = generate_bom(_make_result())
        header = bom_to_csv(bom).splitlines()[0]
        for field in ("id", "label", "part_number", "marking",
                      "value", "package", "datasheet_url", "confidence"):
            assert field in header

    def test_one_component_produces_header_plus_one_row(self):
        bom = generate_bom(_make_result(components=[_make_component("U1")]))
        lines = bom_to_csv(bom).strip().splitlines()
        assert len(lines) == 2

    def test_multiple_components_row_count(self):
        comps = [_make_component(f"R{i}") for i in range(5)]
        bom = generate_bom(_make_result(components=comps))
        lines = bom_to_csv(bom).strip().splitlines()
        assert len(lines) == 6  # header + 5

    def test_component_id_in_csv(self):
        bom = generate_bom(_make_result(components=[_make_component("MYREF")]))
        assert "MYREF" in bom_to_csv(bom)

    def test_part_number_in_csv(self):
        bom = generate_bom(_make_result(components=[_make_component(part_number="LM7805")]))
        assert "LM7805" in bom_to_csv(bom)

    def test_marking_in_csv(self):
        bom = generate_bom(_make_result(components=[_make_component(marking="100nF")]))
        assert "100nF" in bom_to_csv(bom)

    def test_csv_parses_correctly(self):
        comps = [
            _make_component("U1", label="ic", part_number="LM317",
                            marking="317", value="5V", package="TO-92",
                            confidence=0.95),
        ]
        bom = generate_bom(_make_result(components=comps))
        reader = csv.DictReader(io.StringIO(bom_to_csv(bom)))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["id"] == "U1"
        assert rows[0]["label"] == "ic"
        assert rows[0]["part_number"] == "LM317"

    def test_bbox_column_excluded(self):
        bom = generate_bom(_make_result(components=[_make_component()]))
        # bbox should not appear — extrasaction="ignore" drops it
        header = bom_to_csv(bom).splitlines()[0]
        assert "bbox" not in header

    def test_confidence_value_in_row(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.75)]))
        reader = csv.DictReader(io.StringIO(bom_to_csv(bom)))
        rows = list(reader)
        assert float(rows[0]["confidence"]) == 0.75

    def test_commas_in_marking_handled(self):
        bom = generate_bom(_make_result(components=[_make_component(marking='a,b,c')]))
        # CSV should still parse correctly (quoted field)
        reader = csv.DictReader(io.StringIO(bom_to_csv(bom)))
        rows = list(reader)
        assert rows[0]["marking"] == "a,b,c"

    def test_empty_optional_fields_in_csv(self):
        comp = _make_component("X1", part_number="", marking="", value="",
                               package="", datasheet_url="")
        bom = generate_bom(_make_result(components=[comp]))
        reader = csv.DictReader(io.StringIO(bom_to_csv(bom)))
        rows = list(reader)
        assert rows[0]["part_number"] == ""
        assert rows[0]["marking"] == ""


# ---------------------------------------------------------------------------
# bom_to_svg — structure / validity
# ---------------------------------------------------------------------------

class TestBomToSvgValidity:
    def test_returns_string(self):
        bom = generate_bom(_make_result())
        assert isinstance(bom_to_svg(bom), str)

    def test_contains_opening_svg_tag(self):
        bom = generate_bom(_make_result())
        assert "<svg" in bom_to_svg(bom)

    def test_contains_closing_svg_tag(self):
        bom = generate_bom(_make_result())
        assert "</svg>" in bom_to_svg(bom)

    def test_svg_namespace(self):
        bom = generate_bom(_make_result())
        assert 'xmlns="http://www.w3.org/2000/svg"' in bom_to_svg(bom)

    def test_svg_has_width_attribute(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert 'width="900"' in svg

    def test_svg_has_height_attribute(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert 'height="' in svg

    def test_empty_bom_renders_without_crash(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert "<svg" in svg and "</svg>" in svg

    def test_retrace_label_in_header(self):
        bom = generate_bom(_make_result())
        assert "re:trace" in bom_to_svg(bom)

    def test_bill_of_materials_label(self):
        bom = generate_bom(_make_result())
        assert "Bill of Materials" in bom_to_svg(bom)

    def test_version_in_footer(self):
        from retrace import __version__
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert __version__ in svg

    def test_dark_background(self):
        bom = generate_bom(_make_result())
        assert "#0a0e1a" in bom_to_svg(bom)

    def test_column_headers_present(self):
        bom = generate_bom(_make_result(components=[_make_component()]))
        svg = bom_to_svg(bom)
        for col in ("Ref", "Type", "Part Number", "Marking", "Value", "Package", "Confidence"):
            assert col in svg, f"Missing column header: {col}"


# ---------------------------------------------------------------------------
# bom_to_svg — board_name and title params
# ---------------------------------------------------------------------------

class TestBomToSvgParams:
    def test_board_name_shown_in_header(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom, board_name="Xbox One X Motherboard")
        assert "Xbox One X Motherboard" in svg

    def test_empty_board_name_no_crash(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom, board_name="")
        assert "<svg" in svg

    def test_title_param_accepted(self):
        bom = generate_bom(_make_result())
        # title is a legacy/unused param — must not raise
        svg = bom_to_svg(bom, title="Legacy Title")
        assert "<svg" in svg


# ---------------------------------------------------------------------------
# bom_to_svg — summary strip
# ---------------------------------------------------------------------------

class TestBomToSvgSummary:
    def test_total_components_in_summary(self):
        comps = [_make_component(f"U{i}") for i in range(3)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "3 components" in svg

    def test_identified_count_in_summary(self):
        comps = [
            _make_component("U1", part_number="LM317"),
            _make_component("U2", part_number=""),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "1 identified" in svg

    def test_identification_rate_percentage_shown(self):
        comps = [_make_component("U1", part_number="X") for _ in range(10)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "100.0%" in svg

    def test_zero_percent_shown_when_none_identified(self):
        comps = [_make_component(f"C{i}") for i in range(5)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "0.0%" in svg

    def test_footer_shows_totals(self):
        comps = [
            _make_component("U1", part_number="X"),
            _make_component("U2"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        # Footer repeats total and identified
        assert "2 components" in svg
        assert "1 identified" in svg


# ---------------------------------------------------------------------------
# bom_to_svg — component rows and grouping
# ---------------------------------------------------------------------------

class TestBomToSvgComponents:
    def test_component_id_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component("U42")]))
        assert "U42" in bom_to_svg(bom)

    def test_component_label_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(label="capacitor")]))
        assert "capacitor" in bom_to_svg(bom)

    def test_component_part_number_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(part_number="LM7805")]))
        assert "LM7805" in bom_to_svg(bom)

    def test_no_part_number_shows_dash(self):
        bom = generate_bom(_make_result(components=[_make_component(part_number="")]))
        assert "—" in bom_to_svg(bom)

    def test_marking_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(marking="47R")]))
        assert "47R" in bom_to_svg(bom)

    def test_value_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(value="100nF")]))
        assert "100nF" in bom_to_svg(bom)

    def test_package_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(package="SOT-23")]))
        assert "SOT-23" in bom_to_svg(bom)

    def test_confidence_bar_rendered(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.85)]))
        svg = bom_to_svg(bom)
        assert "85%" in svg

    def test_confidence_zero_renders_bar(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.0)]))
        svg = bom_to_svg(bom)
        assert "0%" in svg

    def test_confidence_100_renders_bar(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=1.0)]))
        svg = bom_to_svg(bom)
        assert "100%" in svg

    def test_group_header_for_each_type(self):
        comps = [
            _make_component("U1", label="ic"),
            _make_component("C1", label="capacitor"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        # Group headers use _pretty_type: "Ic" and "Capacitor"
        assert "Ic" in svg
        assert "Capacitor" in svg

    def test_group_header_shows_count(self):
        comps = [
            _make_component("U1", label="ic"),
            _make_component("U2", label="ic"),
            _make_component("C1", label="capacitor"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        # "(2)" for ICs, "(1)" for capacitors
        assert "(2)" in svg
        assert "(1)" in svg

    def test_ics_sorted_before_capacitors(self):
        comps = [
            _make_component("C1", label="capacitor"),
            _make_component("U1", label="ic"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        ic_pos = svg.index("Ic")
        cap_pos = svg.index("Capacitor")
        assert ic_pos < cap_pos, "ICs should appear before capacitors in sorted order"

    def test_unknown_type_sorted_last(self):
        comps = [
            _make_component("U1", label="unknown"),
            _make_component("U2", label="ic"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        ic_pos = svg.index("Ic")
        unknown_pos = svg.index("Unknown")
        assert ic_pos < unknown_pos

    def test_components_within_group_sorted_by_id(self):
        comps = [
            _make_component("U3", label="ic"),
            _make_component("U1", label="ic"),
            _make_component("U2", label="ic"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        u1_pos = svg.index(">U1<")
        u2_pos = svg.index(">U2<")
        u3_pos = svg.index(">U3<")
        assert u1_pos < u2_pos < u3_pos

    def test_test_point_pretty_type(self):
        bom = generate_bom(_make_result(components=[_make_component(label="test_point")]))
        svg = bom_to_svg(bom)
        assert "Test Point" in svg

    def test_multiple_types_all_rendered(self):
        comps = [
            _make_component("U1", label="ic"),
            _make_component("C1", label="capacitor"),
            _make_component("R1", label="resistor"),
            _make_component("J1", label="connector"),
            _make_component("L1", label="inductor"),
            _make_component("X1", label="crystal"),
            _make_component("TP1", label="test_point"),
        ]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        for label in ("Ic", "Capacitor", "Resistor", "Connector",
                      "Inductor", "Crystal", "Test Point"):
            assert label in svg, f"Missing group header for: {label}"

    def test_empty_marking_field_no_crash(self):
        comp = _make_component("U1", marking="")
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "<svg" in svg

    def test_none_not_in_svg_for_empty_fields(self):
        comp = _make_component("U1")
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "None" not in svg


# ---------------------------------------------------------------------------
# bom_to_svg — confidence colour thresholds
# ---------------------------------------------------------------------------

class TestBomToSvgConfidenceColors:
    def test_high_confidence_uses_green(self):
        # > 0.9 → _CONF_GREEN = "#22c55e"
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.95)]))
        svg = bom_to_svg(bom)
        assert "#22c55e" in svg

    def test_medium_confidence_uses_yellow(self):
        # > 0.7 and <= 0.9 → _CONF_YELLOW = "#f59e0b"
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.80)]))
        svg = bom_to_svg(bom)
        assert "#f59e0b" in svg

    def test_low_confidence_uses_red(self):
        # <= 0.7 → _CONF_RED = "#ef4444"
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.50)]))
        svg = bom_to_svg(bom)
        assert "#ef4444" in svg

    def test_confidence_exactly_0_9_uses_yellow(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.9)]))
        svg = bom_to_svg(bom)
        # 0.9 is not > 0.9, falls through to yellow check (> 0.7) → yellow
        assert "#f59e0b" in svg

    def test_confidence_exactly_0_7_uses_red(self):
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.7)]))
        svg = bom_to_svg(bom)
        # 0.7 is not > 0.7, falls through to red
        assert "#ef4444" in svg


# ---------------------------------------------------------------------------
# bom_to_svg — label colours
# ---------------------------------------------------------------------------

class TestBomToSvgLabelColors:
    def test_ic_label_color(self):
        bom = generate_bom(_make_result(components=[_make_component(label="ic")]))
        svg = bom_to_svg(bom)
        assert "#ef4444" in svg  # _LABEL_COLORS["ic"]

    def test_capacitor_label_color(self):
        bom = generate_bom(_make_result(components=[_make_component(label="capacitor")]))
        svg = bom_to_svg(bom)
        assert "#3b82f6" in svg  # _LABEL_COLORS["capacitor"]

    def test_resistor_label_color(self):
        bom = generate_bom(_make_result(components=[_make_component(label="resistor")]))
        svg = bom_to_svg(bom)
        assert "#22c55e" in svg  # _LABEL_COLORS["resistor"]

    def test_connector_label_color(self):
        bom = generate_bom(_make_result(components=[_make_component(label="connector")]))
        svg = bom_to_svg(bom)
        assert "#f59e0b" in svg  # _LABEL_COLORS["connector"]

    def test_unknown_label_color(self):
        bom = generate_bom(_make_result(components=[_make_component(label="unknown")]))
        svg = bom_to_svg(bom)
        assert "#6b7280" in svg  # _LABEL_COLORS["unknown"]

    def test_unrecognised_label_falls_back_to_grey(self):
        bom = generate_bom(_make_result(components=[_make_component(label="mystery_part")]))
        svg = bom_to_svg(bom)
        assert "#6b7280" in svg


# ---------------------------------------------------------------------------
# bom_to_svg — identification rate colour in summary strip
# ---------------------------------------------------------------------------

class TestBomToSvgRateColor:
    def test_high_rate_uses_green(self):
        # > 0.9 → green
        comps = [_make_component(f"U{i}", part_number="X") for i in range(10)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "#22c55e" in svg

    def test_medium_rate_uses_yellow(self):
        comps = [_make_component(f"U{i}", part_number="X") for i in range(8)] + \
                [_make_component(f"U{i}") for i in range(8, 10)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "#f59e0b" in svg

    def test_zero_rate_uses_red(self):
        comps = [_make_component(f"C{i}") for i in range(5)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "#ef4444" in svg


# ---------------------------------------------------------------------------
# bom_to_svg — SVG geometry / height calculation
# ---------------------------------------------------------------------------

class TestBomToSvgGeometry:
    def test_more_components_produce_taller_svg(self):
        few_comps = [_make_component(f"U{i}") for i in range(2)]
        many_comps = [_make_component(f"U{i}") for i in range(20)]
        svg_few = bom_to_svg(generate_bom(_make_result(components=few_comps)))
        svg_many = bom_to_svg(generate_bom(_make_result(components=many_comps)))

        def _extract_height(svg: str) -> int:
            m = re.search(r'height="(\d+)"', svg)
            return int(m.group(1)) if m else 0

        assert _extract_height(svg_many) > _extract_height(svg_few)

    def test_svg_width_is_900(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert 'width="900"' in svg

    def test_viewbox_matches_dimensions(self):
        comps = [_make_component("U1")]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        m_w = re.search(r'width="(\d+)"', svg)
        m_h = re.search(r'height="(\d+)"', svg)
        w, h = int(m_w.group(1)), int(m_h.group(1))
        assert f'viewBox="0 0 {w} {h}"' in svg

    def test_confidence_bar_width_proportional(self):
        # 100% confidence → full bar width (120px)
        bom = generate_bom(_make_result(components=[_make_component(confidence=1.0)]))
        svg = bom_to_svg(bom)
        assert 'width="120"' in svg

    def test_confidence_bar_minimum_width_1(self):
        # 0% confidence → minimum bar width of 1
        bom = generate_bom(_make_result(components=[_make_component(confidence=0.0)]))
        svg = bom_to_svg(bom)
        # bar width = max(1, int(120 * 0.0)) = 1
        assert 'width="1"' in svg


# ---------------------------------------------------------------------------
# bom_to_svg — XSS / security
# ---------------------------------------------------------------------------

class TestBomToSvgSecurity:
    def test_marking_xss_escaped(self):
        comp = _make_component(marking='<script>alert(1)</script>')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_part_number_xss_escaped(self):
        comp = _make_component(part_number='</text><script>evil()</script>')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "<script>" not in svg

    def test_component_id_xss_escaped(self):
        comp = _make_component(cid='"><img src=x onerror=alert(1)>')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        # The < > are escaped so the tag is rendered as text, not injected markup
        assert "<img" not in svg
        assert "&lt;img" in svg

    def test_label_xss_escaped(self):
        comp = _make_component(label='<b>bold</b>')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "<b>" not in svg
        assert "&lt;b&gt;" in svg

    def test_value_xss_escaped(self):
        comp = _make_component(value='<svg onload=alert(1)>')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        # The angle brackets are escaped — no raw <svg …> tag injected
        assert "<svg onload" not in svg
        assert "&lt;svg" in svg

    def test_package_xss_escaped(self):
        # Quotes are escaped so they can't break out of an attribute context
        comp = _make_component(package='"onmouseover="alert(1)"')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        # html.escape converts " to &quot; so the injection is defused
        assert '&quot;onmouseover=' in svg or "onmouseover" not in svg or "&quot;" in svg

    def test_board_name_xss_escaped(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom, board_name='<script>pwned()</script>')
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_ampersand_in_marking_escaped(self):
        comp = _make_component(marking="R&D Part")
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        assert "&amp;" in svg
        assert "R&D" not in svg

    def test_quotes_in_marking_escaped(self):
        comp = _make_component(marking='say "hello"')
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        # html.escape escapes quotes in text nodes as &quot;
        assert "say" in svg

    def test_no_external_hrefs(self):
        comp = _make_component("U1", part_number="LM317")
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        ext_refs = re.findall(r'href="(?!#)', svg)
        assert len(ext_refs) == 0, f"Found external href(s): {ext_refs}"

    def test_no_javascript_protocol(self):
        comp = _make_component("U1", datasheet_url="javascript:alert(1)")
        bom = generate_bom(_make_result(components=[comp]))
        svg = bom_to_svg(bom)
        # datasheet_url doesn't render as a link in SVG — just confirm no JS
        assert "javascript:" not in svg


# ---------------------------------------------------------------------------
# bom_to_svg — edge cases with None / missing fields in bom dict
# ---------------------------------------------------------------------------

class TestBomToSvgEdgeCases:
    def test_bom_with_no_summary_key(self):
        bom = {"components": []}
        svg = bom_to_svg(bom)
        assert "<svg" in svg

    def test_bom_with_empty_components_key(self):
        bom = {"components": [], "summary": {"total_components": 0, "identified": 0,
                                              "identification_rate": 0.0}}
        svg = bom_to_svg(bom)
        assert "<svg" in svg

    def test_bom_missing_component_label_defaults(self):
        bom = {
            "components": [{"id": "X1", "confidence": 0.5, "bbox": [0, 0, 10, 10]}],
            "summary": {},
        }
        # label missing → should fall back to "unknown"
        svg = bom_to_svg(bom)
        assert "<svg" in svg

    def test_confidence_missing_defaults_to_zero(self):
        bom = {
            "components": [{"id": "X1", "label": "ic"}],
            "summary": {},
        }
        svg = bom_to_svg(bom)
        assert "<svg" in svg
        assert "0%" in svg

    def test_very_large_component_list(self):
        comps = [_make_component(f"R{i:04d}", label="resistor") for i in range(200)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "<svg" in svg
        assert "</svg>" in svg
        # All 200 refs should appear
        assert "R0000" in svg
        assert "R0199" in svg

    def test_single_component_renders(self):
        bom = generate_bom(_make_result(components=[_make_component("U1", label="ic",
                                                                     confidence=0.99)]))
        svg = bom_to_svg(bom)
        assert "U1" in svg
        assert "99%" in svg

    def test_all_known_label_types_render(self):
        labels = ["ic", "capacitor", "resistor", "connector",
                  "inductor", "crystal", "header", "test_point", "unknown"]
        comps = [_make_component(f"X{i}", label=lbl) for i, lbl in enumerate(labels)]
        bom = generate_bom(_make_result(components=comps))
        svg = bom_to_svg(bom)
        assert "<svg" in svg and "</svg>" in svg

    def test_pretty_type_underscore_to_space(self):
        bom = generate_bom(_make_result(components=[_make_component(label="test_point")]))
        svg = bom_to_svg(bom)
        assert "Test Point" in svg

    def test_header_label_type_pretty(self):
        bom = generate_bom(_make_result(components=[_make_component(label="header")]))
        svg = bom_to_svg(bom)
        assert "Header" in svg

    def test_empty_result_svg_has_correct_component_count(self):
        bom = generate_bom(_make_result())
        svg = bom_to_svg(bom)
        assert "0 components" in svg
        assert "0 identified" in svg


# ---------------------------------------------------------------------------
# generate_bom — edge cases
# ---------------------------------------------------------------------------

class TestGenerateBomEdgeCases:
    def test_single_component_fully_identified(self):
        comp = _make_component("U1", part_number="LM317")
        bom = generate_bom(_make_result(components=[comp]))
        assert bom["summary"]["total_components"] == 1
        assert bom["summary"]["identified"] == 1
        assert bom["summary"]["identification_rate"] == 1.0

    def test_bom_is_json_serialisable(self):
        comps = [
            _make_component("U1", label="ic", part_number="STM32", confidence=0.99,
                            marking="STM32F103", value="3.3V", package="LQFP-64",
                            datasheet_url="https://st.com/ds.pdf",
                            bbox=(10, 20, 80, 60)),
        ]
        bom = generate_bom(_make_result(components=comps))
        # Must not raise
        json.dumps(bom)

    def test_many_label_types_by_label_dict(self):
        comps = [
            _make_component("U1", label="ic"),
            _make_component("U2", label="ic"),
            _make_component("C1", label="capacitor"),
            _make_component("R1", label="resistor"),
            _make_component("J1", label="connector"),
            _make_component("TP1", label="test_point"),
        ]
        bom = generate_bom(_make_result(components=comps))
        bl = bom["summary"]["by_label"]
        assert bl["ic"] == 2
        assert bl["capacitor"] == 1
        assert bl["resistor"] == 1
        assert bl["connector"] == 1
        assert bl["test_point"] == 1

    def test_traces_counted_correctly(self):
        traces = [_make_trace(f"T{i:08d}") for i in range(3)]
        bom = generate_bom(_make_result(traces=traces))
        assert bom["summary"]["total_traces"] == 3

    def test_zero_duration(self):
        bom = generate_bom(_make_result(duration_seconds=0.0))
        assert bom["metadata"]["duration_seconds"] == 0.0

    def test_large_duration_rounded(self):
        # round(3600.555, 2) yields 3600.55 due to binary float representation
        bom = generate_bom(_make_result(duration_seconds=3600.555))
        assert bom["metadata"]["duration_seconds"] == round(3600.555, 2)
