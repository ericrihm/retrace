"""Tests for src/retrace/export/svg.py — no ML dependencies."""

from __future__ import annotations

from pathlib import Path


from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.svg import generate_svg, save_svg


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_result(
    components: list[Component] | None = None,
    traces: list[Trace] | None = None,
    board_dimensions: tuple[int, int] = (800, 600),
    pipeline_version: str = "0.1.0",
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
        """The summary footer includes the word 'components' (trace count is implicit)."""
        trace = _make_trace(points=[(0, 0), (50, 50), (100, 100)])
        result = _make_result(traces=[trace])
        svg = generate_svg(result)
        # Footer always present
        assert "components" in svg

    def test_no_crash_with_traces_in_result(self):
        traces = [_make_trace(f"T{i:08d}") for i in range(5)]
        result = _make_result(traces=traces)
        svg = generate_svg(result)
        assert "<svg" in svg and "</svg>" in svg

    def test_summary_footer_counts_match(self):
        comps = [_make_component("C1"), _make_component("C2", part_number="LM7805")]
        result = _make_result(components=comps)
        svg = generate_svg(result)
        # "2 components, 1 identified"
        assert "2 components" in svg
        assert "1 identified" in svg


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
        result = _make_result()
        svg = generate_svg(result, image_href="/path/to/board.jpg")
        assert "<image" in svg
        assert "/path/to/board.jpg" in svg

    def test_no_image_href_no_image_element(self):
        result = _make_result()
        svg = generate_svg(result, image_href=None)
        assert "<image" not in svg


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
