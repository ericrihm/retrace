"""Tests for src/retrace/export/svg.py — no ML dependencies."""

from __future__ import annotations

from pathlib import Path

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.svg import (
    _classify_net,
    _edge_point,
    _render_zones,
    _resolve_image_href,
    generate_attack_surface_svg,
    generate_bus_topology_svg,
    generate_diff_svg,
    generate_lineage_svg,
    generate_power_tree_svg,
    generate_svg,
    generate_zones_svg,
    save_svg,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_result(
    components: list[Component] | None = None,
    traces: list[Trace] | None = None,
    board_dimensions: tuple[int, int] = (800, 600),
    pipeline_version: str = "0.3.0",
) -> AnalysisResult:
    return AnalysisResult(
        image_path="test_board.jpg",
        components=components or [],
        traces=traces or [],
        board_dimensions=board_dimensions,
        pipeline_version=pipeline_version,
    )


def _make_component(
    cid: str = "C0001",
    label: str = "ic",
    bbox: tuple[int, int, int, int] = (10, 20, 50, 40),
    part_number: str = "",
    marking: str = "",
) -> Component:
    return Component(
        id=cid,
        label=label,
        confidence=0.9,
        bbox=bbox,
        part_number=part_number,
        marking=marking,
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
# SVG validity
# ---------------------------------------------------------------------------

class TestSvgValidity:
    def test_returns_string(self):
        result = _make_result()
        svg = generate_svg(result)
        assert isinstance(svg, str)

    def test_contains_opening_svg_tag(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "<svg" in svg

    def test_contains_closing_svg_tag(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "</svg>" in svg

    def test_svg_namespace(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_svg_has_width_and_height(self):
        result = _make_result(board_dimensions=(1024, 768))
        svg = generate_svg(result)
        assert 'width="1024"' in svg
        assert 'height="768"' in svg

    def test_explicit_width_height_override(self):
        result = _make_result(board_dimensions=(800, 600))
        svg = generate_svg(result, width=400, height=300)
        assert 'width="400"' in svg
        assert 'height="300"' in svg

    def test_retrace_comment_present(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "re:trace" in svg

    def test_legend_present(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'class="legend"' in svg


# ---------------------------------------------------------------------------
# Component bounding boxes
# ---------------------------------------------------------------------------

class TestComponentAnnotations:
    def test_rect_element_present_for_component(self):
        comp = _make_component(bbox=(10, 20, 50, 40))
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "<rect" in svg

    def test_bbox_coords_in_svg(self):
        comp = _make_component(cid="U1", label="ic", bbox=(15, 25, 60, 45))
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert 'x="15"' in svg
        assert 'y="25"' in svg
        assert 'width="60"' in svg
        assert 'height="45"' in svg

    def test_component_group_element(self):
        comp = _make_component()
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert 'class="component"' in svg

    def test_data_id_attribute(self):
        comp = _make_component(cid="U99")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert 'data-id="U99"' in svg

    def test_data_label_attribute(self):
        comp = _make_component(label="capacitor")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert 'data-label="capacitor"' in svg

    def test_part_number_shown_in_text(self):
        comp = _make_component(part_number="LM1117")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "LM1117" in svg

    def test_marking_shown_when_no_part_number(self):
        comp = _make_component(marking="47R", part_number="")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "47R" in svg

    def test_label_shown_as_fallback(self):
        comp = _make_component(label="resistor", marking="", part_number="")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "resistor" in svg

    def test_label_text_truncated_at_20_chars(self):
        long_label = "A" * 30
        comp = _make_component(part_number=long_label)
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        # Only first 20 chars should appear
        assert "A" * 20 in svg
        assert "A" * 21 not in svg

    def test_multiple_components_produce_multiple_rects(self):
        comps = [
            _make_component("C1", "capacitor", (10, 10, 20, 20)),
            _make_component("C2", "resistor", (100, 100, 30, 15)),
            _make_component("C3", "ic", (200, 50, 80, 60)),
        ]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        rect_count = svg.count("<rect")
        # At least 3 component rects (plus legend rects)
        assert rect_count >= 3

    def test_special_chars_in_id_are_escaped(self):
        comp = _make_component(cid='U<1>&"2"')
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        # Raw unescaped chars should not appear in data-id
        assert '<1>' not in svg


# ---------------------------------------------------------------------------
# Trace paths
# ---------------------------------------------------------------------------

class TestTracePaths:
    def test_footer_shows_trace_count(self):
        trace = _make_trace(points=[(0, 0), (50, 50), (100, 100)])
        result = _make_result(traces=[trace])
        svg = generate_svg(result)
        assert "1 traces" in svg

    def test_no_crash_with_traces_in_result(self):
        traces = [_make_trace(f"T{i:08d}") for i in range(5)]
        result = _make_result(traces=traces)
        svg = generate_svg(result)
        assert "<svg" in svg and "</svg>" in svg

    def test_summary_footer_counts_match(self):
        comps = [_make_component("C1"), _make_component("C2", part_number="LM7805")]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        assert "2 components" in svg
        assert "1 identified" in svg

    def test_trace_polyline_rendered(self):
        trace = _make_trace(points=[(10, 20), (50, 60), (100, 80)])
        result = _make_result(traces=[trace])
        svg = generate_svg(result)
        assert "<polyline" in svg
        assert "10,20" in svg

    def test_trace_group_element(self):
        trace = _make_trace()
        result = _make_result(traces=[trace])
        svg = generate_svg(result)
        assert 'class="traces"' in svg
        assert 'class="trace"' in svg

    def test_pin_dots_rendered(self):
        trace = _make_trace(points=[(10, 20), (100, 100)])
        result = _make_result(traces=[trace])
        svg = generate_svg(result)
        assert svg.count("<circle") >= 2

    def test_trace_with_component_endpoints(self):
        c1 = _make_component("U1", "ic", (10, 10, 60, 60), marking="VRM")
        c2 = _make_component("U2", "ic", (200, 200, 60, 60))
        trace = Trace(id="T001", points=[(40, 40), (230, 230)], width_px=3.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        svg = generate_svg(result)
        assert 'data-net="' in svg

    def test_show_traces_false_hides_traces(self):
        trace = _make_trace()
        result = _make_result(traces=[trace])
        svg = generate_svg(result, show_traces=False)
        assert "<polyline" not in svg
        assert 'class="traces"' not in svg

    def test_net_type_power_classified(self):
        vrm = _make_component("U10", "ic", (10, 10, 50, 50), marking="TPS51611")
        cpu = _make_component("U1", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=5.0,
                      from_component="U10", to_component="U1")
        result = _make_result(components=[vrm, cpu], traces=[trace])
        svg = generate_svg(result)
        assert 'data-net="power"' in svg

    def test_net_type_debug_classified(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        cpu = _make_component("U1", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=2.0,
                      from_component="J5", to_component="U1")
        result = _make_result(components=[jtag, cpu], traces=[trace])
        svg = generate_svg(result)
        assert 'data-net="debug"' in svg

    def test_footer_shows_connection_count(self):
        c1 = _make_component("U1", "ic", (10, 10, 50, 50))
        c2 = _make_component("U2", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=2.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        svg = generate_svg(result)
        assert "1 connections" in svg

    def test_trace_without_points_uses_component_edges(self):
        c1 = _make_component("U1", "ic", (10, 10, 50, 50))
        c2 = _make_component("U2", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[], width_px=2.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        svg = generate_svg(result)
        assert "<line" in svg


# ---------------------------------------------------------------------------
# BOM panel
# ---------------------------------------------------------------------------

class TestBomPanel:
    def test_bom_panel_rendered(self):
        comps = [_make_component("U1", "ic"), _make_component("C1", "capacitor")]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        assert 'class="bom-panel"' in svg
        assert "Bill of Materials" in svg

    def test_bom_shows_component_types(self):
        comps = [
            _make_component("U1", "ic"),
            _make_component("U2", "ic"),
            _make_component("C1", "capacitor"),
        ]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        assert "ic: 2" in svg
        assert "capacitor: 1" in svg

    def test_bom_shows_identified_count(self):
        comps = [
            _make_component("U1", "ic", part_number="LM7805"),
            _make_component("U2", "ic"),
        ]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        assert "1 ID'd" in svg

    def test_bom_shows_totals(self):
        comps = [_make_component("U1"), _make_component("U2"), _make_component("C1", "capacitor")]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        assert "3 parts" in svg

    def test_show_bom_false_hides_panel(self):
        comps = [_make_component("U1")]
        result = _make_result(components=comps)
        svg = generate_svg(result, show_bom=False)
        assert 'class="bom-panel"' not in svg

    def test_bom_not_shown_for_empty_result(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'class="bom-panel"' not in svg


# ---------------------------------------------------------------------------
# Net legend
# ---------------------------------------------------------------------------

class TestNetLegend:
    def test_net_legend_shows_net_types(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "power" in svg
        assert "ground" in svg
        assert "signal" in svg
        assert "debug" in svg

    def test_net_legend_has_line_elements(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "nets:" in svg


# ---------------------------------------------------------------------------
# Empty AnalysisResult
# ---------------------------------------------------------------------------

class TestEmptyResult:
    def test_empty_result_returns_valid_svg(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_empty_result_default_dimensions(self):
        result = AnalysisResult(image_path="x.jpg", board_dimensions=(0, 0))
        svg = generate_svg(result)
        # Falls back to 800×600
        assert 'width="800"' in svg
        assert 'height="600"' in svg

    def test_empty_result_zero_component_footer(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "0 components" in svg

    def test_image_href_embedded(self):
        # Non-existent local path is skipped entirely (SVG stays self-contained)
        result = _make_result()
        svg = generate_svg(result, image_href="/path/to/board.jpg")
        assert "<image" not in svg
        assert "/path/to/board.jpg" not in svg

    def test_no_image_href_no_image_element(self):
        result = _make_result()
        svg = generate_svg(result, image_href=None)
        assert "<image" not in svg


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

class TestSvgSecurity:
    def test_bom_label_xss_escaped(self):
        comp = _make_component("X1", '<script>alert(1)</script>')
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_component_id_xss_escaped(self):
        comp = _make_component(cid='"><script>alert(1)</script>')
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "<script>" not in svg

    def test_marking_xss_escaped(self):
        comp = _make_component(marking='</text><script>x</script>')
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "<script>" not in svg

    def test_javascript_uri_rejected(self):
        result = _make_result()
        svg = generate_svg(result, image_href="javascript:alert(1)")
        assert "<image" not in svg

    def test_javascript_uri_case_insensitive(self):
        result = _make_result()
        svg = generate_svg(result, image_href="  JavaScript:alert(1)")
        assert "<image" not in svg

    def test_valid_image_href_allowed(self):
        result = _make_result()
        svg = generate_svg(result, image_href="data:image/png;base64,abc")
        assert "<image" in svg

    def test_file_path_href_nonexistent_skipped(self):
        # Non-existent local file paths are silently dropped so SVG is self-contained
        result = _make_result()
        svg = generate_svg(result, image_href="/path/to/image.jpg")
        assert "<image" not in svg


# ---------------------------------------------------------------------------
# Dark theme & visual features
# ---------------------------------------------------------------------------

class TestDarkTheme:
    def test_dark_background_present(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'fill="#0a0e1a"' in svg

    def test_grid_pattern_defined(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'id="grid"' in svg
        assert 'url(#grid)' in svg

    def test_glow_filter_defined(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'id="glow-red"' in svg
        assert 'id="glow-purple"' in svg

    def test_arrow_marker_defined(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'id="arrow"' in svg

    def test_title_bar_present(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'class="title-bar"' in svg

    def test_title_bar_shows_custom_title(self):
        result = _make_result()
        svg = generate_svg(result, title="Xbox One X Motherboard")
        assert "Xbox One X Motherboard" in svg

    def test_title_bar_default_text(self):
        result = _make_result()
        svg = generate_svg(result)
        assert "re:trace" in svg

    def test_footer_bar_present(self):
        result = _make_result()
        svg = generate_svg(result)
        assert 'class="footer"' in svg

    def test_component_id_inside_box(self):
        comp = _make_component(cid="U42", label="ic", bbox=(100, 100, 80, 60))
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert "U42" in svg

    def test_legend_has_panel_background(self):
        result = _make_result()
        svg = generate_svg(result)
        lines = svg.split('\n')
        in_legend = False
        has_panel_rect = False
        for line in lines:
            if 'class="legend"' in line:
                in_legend = True
            if in_legend and '<rect' in line and 'fill="#111827"' in line:
                has_panel_rect = True
                break
        assert has_panel_rect


class TestSecurityPanel:
    def test_jtag_component_gets_glow(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        result = _make_result(components=[jtag])
        svg = generate_svg(result)
        assert 'filter="url(#glow-red)"' in svg

    def test_security_panel_rendered_for_jtag(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        result = _make_result(components=[jtag])
        svg = generate_svg(result)
        assert 'class="security-panel"' in svg
        assert "Security Findings" in svg

    def test_security_panel_shows_cwe(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        result = _make_result(components=[jtag])
        svg = generate_svg(result)
        assert "CWE-1191" in svg

    def test_no_security_panel_for_normal_components(self):
        comp = _make_component("C1", "capacitor", (10, 10, 50, 50), marking="100nF")
        result = _make_result(components=[comp])
        svg = generate_svg(result)
        assert 'class="security-panel"' not in svg

    def test_uart_console_detected(self):
        uart = _make_component("J10", "connector", (10, 10, 50, 50), marking="CONSOLE")
        result = _make_result(components=[uart])
        svg = generate_svg(result)
        assert 'class="security-panel"' in svg
        assert "CWE-1299" in svg

    def test_security_badge_on_component(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        result = _make_result(components=[jtag])
        svg = generate_svg(result)
        assert 'fill="#ef4444" fill-opacity="0.9"' in svg


class TestZoneOverlays:
    def test_zones_rendered_when_provided(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        c2 = _make_component("U2", "ic", (200, 100, 80, 60))
        result = _make_result(components=[c1, c2])
        zones = [("CPU Complex", "cpu", ["U1", "U2"])]
        svg = generate_svg(result, zones=zones)
        assert 'class="zones"' in svg
        assert 'data-zone="cpu"' in svg
        assert "CPU COMPLEX" in svg

    def test_no_zones_no_zone_group(self):
        result = _make_result(components=[_make_component()])
        svg = generate_svg(result)
        assert 'class="zones"' not in svg

    def test_empty_zones_list_no_zone_group(self):
        result = _make_result(components=[_make_component()])
        svg = generate_svg(result, zones=[])
        assert 'class="zones"' not in svg

    def test_zone_with_missing_components_skipped(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        result = _make_result(components=[c1])
        zones = [("Ghost Zone", "io", ["NONEXISTENT"])]
        svg = generate_svg(result, zones=zones)
        assert "GHOST ZONE" not in svg

    def test_zone_with_partial_components(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        result = _make_result(components=[c1])
        zones = [("Partial", "memory", ["U1", "MISSING"])]
        svg = generate_svg(result, zones=zones)
        assert 'data-zone="memory"' in svg

    def test_multiple_zones_rendered(self):
        c1 = _make_component("U1", "ic", (50, 50, 80, 60))
        c2 = _make_component("U2", "ic", (200, 200, 80, 60))
        c3 = _make_component("J1", "connector", (400, 400, 60, 40))
        result = _make_result(components=[c1, c2, c3])
        zones = [
            ("CPU", "cpu", ["U1"]),
            ("Memory", "memory", ["U2"]),
            ("I/O", "io", ["J1"]),
        ]
        svg = generate_svg(result, zones=zones)
        assert 'data-zone="cpu"' in svg
        assert 'data-zone="memory"' in svg
        assert 'data-zone="io"' in svg

    def test_zone_uses_correct_color(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        result = _make_result(components=[c1])
        zones = [("Power", "power", ["U1"])]
        svg = generate_svg(result, zones=zones)
        assert "#f59e0b" in svg

    def test_zone_xss_escaped(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        result = _make_result(components=[c1])
        zones = [('<script>alert(1)</script>', "cpu", ["U1"])]
        svg = generate_svg(result, zones=zones)
        assert "<script>" not in svg
        assert "&lt;SCRIPT&gt;" in svg

    def test_zone_dashed_border(self):
        c1 = _make_component("U1", "ic", (100, 100, 80, 60))
        result = _make_result(components=[c1])
        zones = [("Test", "cpu", ["U1"])]
        svg = generate_svg(result, zones=zones)
        assert 'stroke-dasharray="6,4"' in svg

    def test_zones_rendered_before_traces(self):
        c1 = _make_component("U1", "ic", (10, 10, 50, 50))
        c2 = _make_component("U2", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=2.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        zones = [("CPU", "cpu", ["U1"])]
        svg = generate_svg(result, zones=zones)
        zone_pos = svg.index('class="zones"')
        trace_pos = svg.index('class="traces"')
        assert zone_pos < trace_pos


class TestTraceEnhancements:
    def test_debug_trace_has_dash(self):
        jtag = _make_component("J5", "connector", (10, 10, 50, 50), marking="JTAG")
        cpu = _make_component("U1", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=2.0,
                      from_component="J5", to_component="U1")
        result = _make_result(components=[jtag, cpu], traces=[trace])
        svg = generate_svg(result)
        assert 'stroke-dasharray="6,3"' in svg

    def test_connected_trace_has_arrow(self):
        c1 = _make_component("U1", "ic", (10, 10, 50, 50))
        c2 = _make_component("U2", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=2.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        svg = generate_svg(result)
        assert 'marker-end="url(#arrow)"' in svg

    def test_net_label_at_midpoint(self):
        c1 = _make_component("U1", "ic", (10, 10, 50, 50))
        c2 = _make_component("U2", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (120, 120), (225, 225)], width_px=2.0,
                      from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[trace])
        svg = generate_svg(result)
        assert "SIGNAL" in svg

    def test_power_trace_has_glow(self):
        vrm = _make_component("U10", "ic", (10, 10, 50, 50), marking="TPS51611")
        cpu = _make_component("U1", "ic", (200, 200, 50, 50))
        trace = Trace(id="T001", points=[(35, 35), (225, 225)], width_px=5.0,
                      from_component="U10", to_component="U1")
        result = _make_result(components=[vrm, cpu], traces=[trace])
        svg = generate_svg(result)
        assert 'filter="url(#glow-red)"' in svg


# ---------------------------------------------------------------------------
# save_svg writes to file
# ---------------------------------------------------------------------------

class TestSaveSvg:
    def test_save_svg_creates_file(self, tmp_path: Path):
        result = _make_result()
        output = tmp_path / "output.svg"
        save_svg(result, str(output))
        assert output.exists()

    def test_save_svg_file_not_empty(self, tmp_path: Path):
        result = _make_result(components=[_make_component()])
        output = tmp_path / "board.svg"
        save_svg(result, str(output))
        content = output.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_save_svg_content_matches_generate(self, tmp_path: Path):
        result = _make_result(components=[_make_component()])
        output = tmp_path / "board.svg"
        save_svg(result, str(output))
        expected = generate_svg(result)
        actual = output.read_text(encoding="utf-8")
        assert actual == expected

    def test_save_svg_overwrites_existing(self, tmp_path: Path):
        output = tmp_path / "board.svg"
        output.write_text("old content", encoding="utf-8")
        result = _make_result()
        save_svg(result, str(output))
        content = output.read_text(encoding="utf-8")
        assert "old content" not in content
        assert "<svg" in content

    def test_save_svg_passes_kwargs(self, tmp_path: Path):
        result = _make_result(board_dimensions=(1920, 1080))
        output = tmp_path / "wide.svg"
        save_svg(result, str(output), width=640, height=480)
        content = output.read_text(encoding="utf-8")
        assert 'width="640"' in content
        assert 'height="480"' in content

    def test_save_svg_utf8_encoding(self, tmp_path: Path):
        comp = _make_component(marking="100µF")
        result = _make_result(components=[comp])
        output = tmp_path / "utf8.svg"
        save_svg(result, str(output))
        content = output.read_bytes()
        # µ is a multi-byte UTF-8 character — just verify file is readable
        decoded = content.decode("utf-8")
        assert "<svg" in decoded


# ---------------------------------------------------------------------------
# Attack Surface SVG
# ---------------------------------------------------------------------------

class TestAttackSurfaceSvg:
    def _security_setup(self):
        jtag = _make_component("J5", "connector", (10, 800, 100, 40), marking="JTAG")
        cpu = _make_component("U1", "ic", (300, 300, 200, 200))
        fpga = _make_component("U6", "ic", (600, 300, 150, 150), marking="XC6SLX45")
        spi = _make_component("U7", "ic", (700, 100, 80, 40), marking="W25Q128")
        cap = _make_component("C1", "capacitor", (100, 100, 20, 10))
        result = _make_result(components=[jtag, cpu, fpga, spi, cap])
        attack_paths = [
            ("J5", "U1", "JTAG debug access"),
            ("U1", "U6", "CPU to FPGA"),
            ("U7", "U6", "SPI flash to FPGA"),
        ]
        security_refs = ["J5", "U1", "U6", "U7"]
        return result, attack_paths, security_refs

    def test_returns_valid_svg(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_contains_attack_paths_group(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        assert "attack-path" in svg or "attack_path" in svg or "Attack Surface" in svg

    def test_dimmed_components_present(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        assert "opacity" in svg

    def test_security_refs_highlighted(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        assert "glow-red" in svg

    def test_attack_path_labels_present(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        assert "JTAG debug access" in svg or "JTAG" in svg

    def test_title_shown(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs, title="Cisco ASA Attack Surface")
        assert "Cisco ASA Attack Surface" in svg or "Attack Surface" in svg

    def test_no_external_refs(self):
        import re
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs)
        ext = re.findall(r'href="(?!data:|#)', svg)
        assert len(ext) == 0

    def test_empty_attack_paths(self):
        result = _make_result(components=[_make_component()])
        svg = generate_attack_surface_svg(result, [], [])
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_missing_component_in_path_no_crash(self):
        result = _make_result(components=[_make_component("U1")])
        svg = generate_attack_surface_svg(
            result, [("U1", "NONEXISTENT", "broken path")], ["U1"]
        )
        assert "<svg" in svg

    def test_custom_dimensions(self):
        result, paths, refs = self._security_setup()
        svg = generate_attack_surface_svg(result, paths, refs, width=1024, height=768)
        assert 'width="1024"' in svg
        assert 'height="768"' in svg


# ---------------------------------------------------------------------------
# Zones SVG
# ---------------------------------------------------------------------------

class TestZonesSvg:
    def _zones_setup(self):
        cpu = _make_component("U1", "ic", (300, 300, 200, 200))
        mem1 = _make_component("U2", "ic", (100, 100, 120, 70))
        mem2 = _make_component("U3", "ic", (100, 250, 120, 70))
        pwr = _make_component("VRM1", "ic", (600, 600, 80, 60))
        result = _make_result(components=[cpu, mem1, mem2, pwr])
        zones = [
            ("CPU Complex", "cpu", ["U1"]),
            ("Memory Bank", "memory", ["U2", "U3"]),
            ("Power", "power", ["VRM1"]),
        ]
        return result, zones

    def test_returns_valid_svg(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_zone_names_present(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        assert "CPU" in svg
        assert "Memory" in svg or "MEMORY" in svg
        assert "Power" in svg or "POWER" in svg

    def test_zone_rects_present(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        assert 'class="zone"' in svg or 'data-zone=' in svg

    def test_components_dimmed(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        assert "opacity" in svg

    def test_no_trace_clutter(self):
        cpu = _make_component("U1", "ic", (300, 300, 200, 200))
        trace = Trace(id="T001", points=[(350, 350), (500, 500)], width_px=2.0,
                      from_component="U1", to_component="U1")
        result = _make_result(components=[cpu], traces=[trace])
        zones = [("CPU", "cpu", ["U1"])]
        svg = generate_zones_svg(result, zones)
        assert 'class="traces"' not in svg

    def test_title_shown(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones, title="Xbox Functional Zones")
        assert "Xbox Functional Zones" in svg or "Zone Map" in svg

    def test_no_external_refs(self):
        import re
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        ext = re.findall(r'href="(?!data:|#)', svg)
        assert len(ext) == 0

    def test_empty_zones(self):
        result = _make_result(components=[_make_component()])
        svg = generate_zones_svg(result, [])
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_custom_dimensions(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones, width=1920, height=1080)
        assert 'width="1920"' in svg
        assert 'height="1080"' in svg

    def test_zone_component_count(self):
        result, zones = self._zones_setup()
        svg = generate_zones_svg(result, zones)
        assert "2" in svg  # Memory Bank has 2 components


# ---------------------------------------------------------------------------
# _classify_net branch coverage
# ---------------------------------------------------------------------------

class TestClassifyNet:
    """Cover the remaining _classify_net branches (lines 98-107)."""

    def _trace(self, width_px: float = 2.0, from_c: str = "", to_c: str = "") -> Trace:
        return Trace(id="T001", points=[(0, 0), (100, 100)],
                     width_px=width_px, from_component=from_c, to_component=to_c)

    def _comp(self, cid: str, marking: str = "", label: str = "ic") -> Component:
        return Component(id=cid, label=label, confidence=0.9,
                         bbox=(10, 10, 50, 50), marking=marking)

    def test_wide_trace_classified_as_power(self):
        trace = self._trace(width_px=6.0)
        net = _classify_net(trace, {})
        assert net == "power"

    def test_width_exactly_5_is_power(self):
        trace = self._trace(width_px=5.0)
        net = _classify_net(trace, {})
        assert net == "power"

    def test_inductor_with_width4_is_power(self):
        ind = self._comp("L1", marking="inductor", label="inductor")
        trace = self._trace(width_px=4.0, from_c="L1")
        net = _classify_net(trace, {"L1": ind})
        assert net == "power"

    def test_clk_marking_classified_as_clock(self):
        clk = self._comp("U1", marking="CLK")
        trace = self._trace(width_px=1.0, from_c="U1")
        net = _classify_net(trace, {"U1": clk})
        assert net == "clock"

    def test_ddr_marking_classified_as_data(self):
        mem = self._comp("U2", marking="DDR4")
        trace = self._trace(width_px=1.0, from_c="U2")
        net = _classify_net(trace, {"U2": mem})
        assert net == "data"

    def test_gnd_marking_classified_as_ground(self):
        gnd = self._comp("J1", marking="GND")
        trace = self._trace(width_px=1.0, from_c="J1")
        net = _classify_net(trace, {"J1": gnd})
        assert net == "ground"


# ---------------------------------------------------------------------------
# _edge_point branch coverage
# ---------------------------------------------------------------------------

class TestEdgePoint:
    """Cover the degenerate branches of _edge_point (lines 122-135)."""

    def _comp(self, x: int, y: int, w: int, h: int) -> Component:
        return Component(id="C1", label="ic", confidence=0.9,
                         bbox=(x, y, w, h))

    def test_near_zero_delta_returns_top_center(self):
        # dx < 1 and dy < 1 -> returns (cx, y)
        comp = self._comp(100, 200, 50, 40)
        cx = 100 + 50 // 2  # 125
        cy = 200 + 40 // 2  # 220
        # Target is effectively the same as center
        result = _edge_point(comp, cx, cy)
        assert result == (cx, 200)  # (cx, y)

    def test_zero_size_component_returns_center(self):
        # w=0 h=0 -> returns (cx, cy)
        comp = self._comp(100, 200, 0, 0)
        result = _edge_point(comp, 200, 300)
        assert result == (100, 200)  # (cx, cy) when w=0 h=0


# ---------------------------------------------------------------------------
# _render_zones direct call coverage
# ---------------------------------------------------------------------------

class TestRenderZonesDirect:
    """Cover _render_zones with empty list (line 536)."""

    def test_empty_zones_returns_empty_string(self):
        result = _render_zones([], {})
        assert result == ""

    def test_zone_with_no_valid_members_skipped(self):
        # All comp_ids are missing from comp_map -> members is empty -> continue
        comp_map = {}
        zones = [("Ghost", "cpu", ["MISSING1", "MISSING2"])]
        out = _render_zones(zones, comp_map)
        # The outer group is created but no zone rect is added
        assert "GHOST" not in out


# ---------------------------------------------------------------------------
# _resolve_image_href coverage (lines 1607-1626)
# ---------------------------------------------------------------------------

class TestResolveImageHref:
    """Cover all branches of _resolve_image_href."""

    def test_none_returns_none(self):
        assert _resolve_image_href(None) is None

    def test_javascript_uri_returns_none(self):
        assert _resolve_image_href("javascript:alert(1)") is None

    def test_javascript_uri_case_insensitive(self):
        assert _resolve_image_href("  JAVASCRIPT:evil()") is None

    def test_http_url_returned_as_is(self):
        url = "http://example.com/board.jpg"
        assert _resolve_image_href(url) == url

    def test_https_url_returned_as_is(self):
        url = "https://example.com/board.png"
        assert _resolve_image_href(url) == url

    def test_data_uri_returned_as_is(self):
        uri = "data:image/png;base64,abc123"
        assert _resolve_image_href(uri) == uri

    def test_nonexistent_local_file_returns_none(self):
        assert _resolve_image_href("/nonexistent/path/board.jpg") is None

    def test_existing_local_file_returns_data_uri(self, tmp_path: Path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        result = _resolve_image_href(str(img))
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    def test_existing_jpg_file_uses_jpeg_mime(self, tmp_path: Path):
        img = tmp_path / "board.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 8)
        result = _resolve_image_href(str(img))
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_unknown_extension_defaults_to_png_mime(self, tmp_path: Path):
        img = tmp_path / "board.bmp"
        img.write_bytes(b"BM" + b"\x00" * 10)
        result = _resolve_image_href(str(img))
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    def test_generate_svg_embeds_local_file(self, tmp_path: Path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        result = _make_result()
        svg = generate_svg(result, image_href=str(img))
        assert "<image" in svg
        assert "data:image/png;base64," in svg


# ---------------------------------------------------------------------------
# Power tree diagram tests
# ---------------------------------------------------------------------------

class TestPowerTree:

    def test_empty_result_returns_empty(self):
        result = _make_result(components=[])
        svg = generate_power_tree_svg(result)
        assert svg == ""

    def test_no_regulators_returns_empty(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="ARM CPU")
        result = _make_result(components=[c])
        svg = generate_power_tree_svg(result)
        assert svg == ""

    def test_vrm_creates_power_tree(self):
        vrm = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="VRM buck 3.3V")
        cpu = Component(id="U2", label="ic", confidence=0.9,
                        bbox=(200, 200, 60, 40), marking="ARM CPU")
        result = _make_result(components=[vrm, cpu])
        svg = generate_power_tree_svg(result)
        assert svg
        assert "<svg" in svg
        assert "Power Delivery Topology" in svg
        assert "REGULATORS" in svg
        assert "LOADS" in svg

    def test_power_tree_with_capacitors(self):
        vrm = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="LDO regulator")
        cap = Component(id="C1", label="capacitor", confidence=0.9,
                        bbox=(80, 80, 10, 10), value="10uF")
        result = _make_result(components=[vrm, cap])
        svg = generate_power_tree_svg(result)
        assert svg
        assert "Decoupling" in svg

    def test_power_tree_custom_width(self):
        vrm = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="PMIC")
        result = _make_result(components=[vrm])
        svg = generate_power_tree_svg(result, width=1000)
        assert 'width="1000"' in svg

    def test_power_tree_with_input_source(self):
        vin = Component(id="J1", label="connector", confidence=0.9,
                        bbox=(5, 5, 20, 20), marking="VIN barrel jack")
        vrm = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(100, 100, 50, 50), marking="buck regulator")
        result = _make_result(components=[vin, vrm])
        svg = generate_power_tree_svg(result)
        assert svg
        assert "INPUT" in svg


# ---------------------------------------------------------------------------
# Bus topology graph tests
# ---------------------------------------------------------------------------

class TestBusTopology:

    def test_no_traces_returns_empty(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="MCU")
        result = _make_result(components=[c], traces=[])
        svg = generate_bus_topology_svg(result)
        assert svg == ""

    def test_no_bus_match_returns_empty(self):
        c1 = Component(id="U1", label="ic", confidence=0.9,
                       bbox=(10, 10, 50, 50), marking="generic chip")
        c2 = Component(id="U2", label="ic", confidence=0.9,
                       bbox=(200, 200, 50, 50), marking="other chip")
        t = Trace(id="T1", points=[(10, 10)], width_px=1.0,
                  from_component="U1", to_component="U2")
        result = _make_result(components=[c1, c2], traces=[t])
        svg = generate_bus_topology_svg(result)
        assert svg == ""

    def test_spi_bus_detected(self):
        mcu = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="STM32 SPI master")
        flash = Component(id="U2", label="ic", confidence=0.9,
                          bbox=(200, 200, 50, 50), marking="W25Q128 flash")
        t = Trace(id="T1", points=[(10, 10)], width_px=1.0,
                  from_component="U1", to_component="U2")
        result = _make_result(components=[mcu, flash], traces=[t])
        svg = generate_bus_topology_svg(result)
        assert svg
        assert "SPI" in svg
        assert "Bus Topology" in svg

    def test_multiple_buses(self):
        mcu = Component(id="U1", label="mcu", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="MCU UART console")
        eeprom = Component(id="U2", label="ic", confidence=0.9,
                           bbox=(200, 200, 50, 50), marking="AT24C256 eeprom")
        debug = Component(id="J1", label="connector", confidence=0.9,
                          bbox=(300, 300, 20, 20), marking="JTAG header")
        t1 = Trace(id="T1", points=[], width_px=1.0,
                   from_component="U1", to_component="U2")
        t2 = Trace(id="T2", points=[], width_px=1.0,
                   from_component="U1", to_component="J1")
        result = _make_result(components=[mcu, eeprom, debug], traces=[t1, t2])
        svg = generate_bus_topology_svg(result)
        assert svg
        assert "I2C" in svg
        assert "JTAG" in svg

    def test_custom_width(self):
        mcu = Component(id="U1", label="ic", confidence=0.9,
                        bbox=(10, 10, 50, 50), marking="USB hub")
        dev = Component(id="U2", label="ic", confidence=0.9,
                        bbox=(200, 200, 50, 50), marking="USB device")
        t = Trace(id="T1", points=[], width_px=1.0,
                  from_component="U1", to_component="U2")
        result = _make_result(components=[mcu, dev], traces=[t])
        svg = generate_bus_topology_svg(result, width=1000)
        assert 'width="1000"' in svg


class TestDiffSvg:
    def test_identical_results_returns_empty(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="STM32")
        a = _make_result(components=[c])
        b = _make_result(components=[c])
        assert generate_diff_svg(a, b) == ""

    def test_added_components_shown_green(self):
        a = _make_result(components=[])
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="STM32")
        b = _make_result(components=[c])
        svg = generate_diff_svg(a, b)
        assert svg
        assert "ADDED" in svg
        assert "#22c55e" in svg

    def test_removed_components_shown_red(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="STM32")
        a = _make_result(components=[c])
        b = _make_result(components=[])
        svg = generate_diff_svg(a, b)
        assert svg
        assert "REMOVED" in svg
        assert "#ef4444" in svg

    def test_changed_components_shown_amber(self):
        c1 = Component(id="U1", label="ic", confidence=0.9,
                       bbox=(10, 10, 50, 50), marking="STM32F103")
        c2 = Component(id="U1", label="ic", confidence=0.9,
                       bbox=(10, 10, 50, 50), marking="STM32F407")
        a = _make_result(components=[c1])
        b = _make_result(components=[c2])
        svg = generate_diff_svg(a, b)
        assert svg
        assert "CHANGED" in svg
        assert "#f59e0b" in svg

    def test_unchanged_not_shown_just_counted(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="STM32")
        c_new = Component(id="U2", label="ic", confidence=0.9,
                          bbox=(20, 20, 50, 50), marking="ESP32")
        a = _make_result(components=[c])
        b = _make_result(components=[c, c_new])
        svg = generate_diff_svg(a, b)
        assert "1 unchanged" in svg

    def test_custom_labels(self):
        c = Component(id="U1", label="ic", confidence=0.9,
                      bbox=(10, 10, 50, 50), marking="old")
        c2 = Component(id="U2", label="ic", confidence=0.9,
                       bbox=(20, 20, 50, 50), marking="new")
        a = _make_result(components=[c])
        b = _make_result(components=[c, c2])
        svg = generate_diff_svg(a, b, label_a="Rev A", label_b="Rev B")
        assert "Rev A" in svg
        assert "Rev B" in svg


class TestLineageSvg:
    def test_empty_boards_returns_empty(self):
        assert generate_lineage_svg({}, []) == ""

    def test_single_board_returns_empty(self):
        assert generate_lineage_svg({"board1": 50}, []) == ""

    def test_two_boards_with_edge(self):
        boards = {"Cisco ASA": 177, "Xbox One": 150}
        edges = [("Cisco ASA", "Xbox One", 0.45)]
        svg = generate_lineage_svg(boards, edges)
        assert svg
        assert "Cisco ASA" in svg
        assert "Xbox One" in svg
        assert "45%" in svg
        assert "Cross-Board Lineage" in svg

    def test_edge_thickness_scales_with_score(self):
        boards = {"A": 10, "B": 20, "C": 30}
        edges = [("A", "B", 0.9), ("A", "C", 0.2)]
        svg = generate_lineage_svg(boards, edges)
        assert svg
        assert 'stroke-width="5"' in svg  # 0.9 * 6 ≈ 5
        assert 'stroke-width="1"' in svg  # 0.2 * 6 ≈ 1
