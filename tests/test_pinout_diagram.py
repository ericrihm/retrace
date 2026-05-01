"""Tests for pinout diagram generator."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.pinout_diagram import (
    _GROUP_COLORS,
    _PINOUTS,
    _PROBE_GUIDES,
    _best_pinout,
    _crop_to_base64,
    _detect_pin_count,
    _is_dual_row,
    _pin_positions_in_crop,
    generate_all_pinout_svgs,
    generate_pinout_svg,
    save_pinout_svg,
)


def _make_result(**kwargs) -> AnalysisResult:
    defaults = dict(
        image_path="/tmp/test_board.jpg",
        components=[
            Component(id="J5", label="header", confidence=0.95,
                      bbox=(200, 150, 60, 140), marking="JTAG20"),
            Component(id="U1", label="ic", confidence=0.9,
                      bbox=(100, 100, 80, 80), marking="STM32F407"),
            Component(id="J3", label="connector", confidence=0.85,
                      bbox=(350, 200, 40, 30), marking="UART"),
        ],
        traces=[
            Trace(id="T1", points=[(230, 220), (140, 140)],
                  from_component="J5", to_component="U1"),
        ],
        board_dimensions=(800, 600),
    )
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


def _make_finding(interface="JTAG", comp_id="J5", **kwargs):
    base = {
        "type": "debug_interface",
        "interface": interface,
        "severity": "high",
        "description": f"{interface} debug interface",
        "component_id": comp_id,
        "component_label": "header",
        "component_marking": interface,
        "cve_reference": "CWE-1191",
        "cvss_base": 7.6,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "mitre_attack": ["T1200", "T0839"],
    }
    base.update(kwargs)
    return base


# ── Pinout data tests ────────────────────────────────────────────────


class TestPinoutData:
    def test_all_interfaces_have_pinouts(self):
        for iface in ("JTAG", "SWD", "UART", "SPI", "I2C"):
            assert iface in _PINOUTS

    def test_pinout_entries_have_three_fields(self):
        for iface, pin_counts in _PINOUTS.items():
            for count, pins in pin_counts.items():
                assert len(pins) == count, f"{iface} {count}-pin has {len(pins)} entries"
                for name, group, desc in pins:
                    assert name, f"Empty pin name in {iface} {count}-pin"
                    assert group in _GROUP_COLORS, f"Unknown group {group!r} in {iface}"
                    assert desc, f"Empty description in {iface} {count}-pin"

    def test_probe_guides_exist_for_all_interfaces(self):
        for iface in ("JTAG", "SWD", "UART", "SPI", "I2C"):
            assert iface in _PROBE_GUIDES
            assert len(_PROBE_GUIDES[iface]) >= 1

    def test_probe_guide_entries_are_tuples(self):
        for iface, probes in _PROBE_GUIDES.items():
            for probe_name, wires in probes.items():
                assert probe_name
                for target, probe in wires:
                    assert target
                    assert probe

    def test_jtag_20pin_standard_layout(self):
        pins = _PINOUTS["JTAG"][20]
        names = [p[0] for p in pins]
        assert names[0] == "VTref"
        assert "TDI" in names
        assert "TDO" in names
        assert "TCK" in names
        assert "TMS" in names
        assert names.count("GND") == 9

    def test_uart_4pin_layout(self):
        pins = _PINOUTS["UART"][4]
        names = [p[0] for p in pins]
        assert "TX" in names
        assert "RX" in names
        assert "GND" in names

    def test_spi_has_flashrom_guide(self):
        assert "flashrom" in _PROBE_GUIDES["SPI"]


# ── Helper function tests ────────────────────────────────────────────


class TestHelpers:
    def test_is_dual_row_jtag_20(self):
        assert _is_dual_row("JTAG", 20) is True

    def test_is_dual_row_jtag_10(self):
        assert _is_dual_row("JTAG", 10) is True

    def test_is_dual_row_uart_4(self):
        assert _is_dual_row("UART", 4) is False

    def test_is_dual_row_spi_8(self):
        assert _is_dual_row("SPI", 8) is True

    def test_is_dual_row_i2c_2(self):
        assert _is_dual_row("I2C", 2) is False

    def test_best_pinout_exact_match(self):
        pins = _best_pinout("JTAG", 20)
        assert len(pins) == 20

    def test_best_pinout_closest_match(self):
        pins = _best_pinout("JTAG", 12)
        assert len(pins) == 12

    def test_best_pinout_unknown_interface(self):
        pins = _best_pinout("UNKNOWN", 4)
        assert len(pins) == 4
        assert all(p[0] == "?" for p in pins)

    def test_detect_pin_count_from_marking(self):
        comp = Component(id="J1", label="header", confidence=0.9,
                         bbox=(0, 0, 60, 120), marking="JTAG 20")
        assert _detect_pin_count(comp, "JTAG") == 20

    def test_detect_pin_count_from_package(self):
        comp = Component(id="J1", label="header", confidence=0.9,
                         bbox=(0, 0, 60, 120), marking="debug",
                         package="10-pin")
        assert _detect_pin_count(comp, "SWD") == 10

    def test_detect_pin_count_fallback(self):
        comp = Component(id="J1", label="header", confidence=0.9,
                         bbox=(0, 0, 60, 120), marking="debug")
        count = _detect_pin_count(comp, "UART")
        assert count in _PINOUTS["UART"]


class TestPinPositions:
    def test_dual_row_positions_count(self):
        positions = _pin_positions_in_crop(10, 10, 60, 120, 20, dual_row=True)
        assert len(positions) == 20

    def test_single_row_horizontal(self):
        positions = _pin_positions_in_crop(10, 10, 120, 30, 4, dual_row=False)
        assert len(positions) == 4
        ys = [p[1] for p in positions]
        assert len(set(ys)) == 1

    def test_single_row_vertical(self):
        positions = _pin_positions_in_crop(10, 10, 30, 120, 4, dual_row=False)
        assert len(positions) == 4
        xs = [p[0] for p in positions]
        assert len(set(xs)) == 1

    def test_dual_row_two_columns(self):
        positions = _pin_positions_in_crop(10, 10, 60, 120, 10, dual_row=True)
        left_x = {positions[i][0] for i in range(0, 10, 2)}
        right_x = {positions[i][0] for i in range(1, 10, 2)}
        assert len(left_x) == 1
        assert len(right_x) == 1
        assert left_x.pop() < right_x.pop()

    def test_positions_within_bounds(self):
        positions = _pin_positions_in_crop(20, 20, 80, 160, 20, dual_row=True)
        for px, py in positions:
            assert 20 <= px <= 100
            assert 20 <= py <= 180


# ── Image cropping tests ─────────────────────────────────────────────


class TestCropping:
    def test_crop_nonexistent_image(self):
        b64, crop_bbox = _crop_to_base64("/nonexistent/image.jpg", (100, 100, 50, 50))
        assert b64 is None
        assert crop_bbox == (0, 0, 0, 0)

    def test_crop_real_image(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (800, 600), color=(50, 50, 50))
        img_path = tmp_path / "board.png"
        img.save(str(img_path))

        b64, (cx, cy, cw, ch) = _crop_to_base64(str(img_path), (200, 150, 60, 120))
        assert b64 is not None
        assert len(b64) > 100
        assert cx < 200
        assert cy < 150
        assert cw > 60
        assert ch > 120

    def test_crop_clamps_to_image_bounds(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(50, 50, 50))
        img_path = tmp_path / "small.png"
        img.save(str(img_path))

        b64, (cx, cy, cw, ch) = _crop_to_base64(str(img_path), (10, 10, 80, 80))
        assert b64 is not None
        assert cx >= 0
        assert cy >= 0
        assert cx + cw <= 100
        assert cy + ch <= 100


# ── SVG generation tests ─────────────────────────────────────────────


class TestSvgGeneration:
    def test_basic_svg_structure(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
        assert "re:trace" in svg
        assert "JTAG" in svg

    def test_svg_contains_pin_labels(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "TDI" in svg
        assert "TDO" in svg
        assert "TCK" in svg
        assert "TMS" in svg

    def test_svg_contains_probe_guide(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "Probe Connection Guide" in svg
        assert "J-Link" in svg

    def test_svg_contains_notes(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "voltage" in svg.lower()

    def test_svg_contains_cvss(self):
        result = _make_result()
        finding = _make_finding(cvss_base=7.6)
        svg = generate_pinout_svg(result, finding)
        assert "CVSS 7.6" in svg

    def test_svg_contains_legend(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        for group in _GROUP_COLORS:
            assert group in svg

    def test_svg_pin1_indicator(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert 'stroke-dasharray="3,2"' in svg

    def test_uart_svg(self):
        result = _make_result()
        finding = _make_finding(interface="UART", comp_id="J3",
                                cvss_base=6.8, severity="medium")
        svg = generate_pinout_svg(result, finding)
        assert "UART" in svg
        assert "TX" in svg
        assert "RX" in svg
        assert "baud" in svg.lower()

    def test_swd_svg(self):
        result = _make_result()
        finding = _make_finding(interface="SWD")
        svg = generate_pinout_svg(result, finding)
        assert "SWD" in svg
        assert "SWDIO" in svg
        assert "SWCLK" in svg

    def test_spi_svg(self):
        result = _make_result()
        finding = _make_finding(interface="SPI", severity="medium", cvss_base=5.3)
        svg = generate_pinout_svg(result, finding)
        assert "SPI" in svg
        assert "MOSI" in svg
        assert "flashrom" in svg

    def test_i2c_svg(self):
        result = _make_result()
        finding = _make_finding(interface="I2C", severity="low", cvss_base=3.5)
        svg = generate_pinout_svg(result, finding)
        assert "I2C" in svg
        assert "SCL" in svg
        assert "SDA" in svg

    def test_svg_with_real_image(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (800, 600), color=(30, 40, 50))
        img_path = tmp_path / "board.png"
        img.save(str(img_path))

        result = _make_result(image_path=str(img_path))
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "data:image/png;base64," in svg

    def test_svg_without_image_uses_schematic(self):
        result = _make_result(image_path="/nonexistent/board.jpg")
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "header" in svg
        assert "<svg" in svg

    def test_svg_escapes_html(self):
        result = _make_result(components=[
            Component(id="J5", label="header", confidence=0.95,
                      bbox=(200, 150, 60, 140), marking='<script>alert("xss")</script>'),
        ])
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_custom_width(self):
        result = _make_result()
        finding = _make_finding()
        svg = generate_pinout_svg(result, finding, width=1024)
        assert 'width="1024"' in svg

    def test_missing_component_uses_first(self):
        result = _make_result()
        finding = _make_finding(comp_id="NONEXISTENT")
        svg = generate_pinout_svg(result, finding)
        assert "<svg" in svg

    def test_empty_result_creates_synthetic(self):
        result = _make_result(components=[])
        finding = _make_finding(comp_id="J1")
        svg = generate_pinout_svg(result, finding)
        assert "<svg" in svg


class TestBatchGeneration:
    def test_generate_all_filters_by_type(self):
        result = _make_result()
        findings = [
            _make_finding(interface="JTAG"),
            _make_finding(interface="UART", comp_id="J3"),
            {"type": "other_finding", "severity": "low"},
        ]
        diagrams = generate_all_pinout_svgs(result, findings)
        assert len(diagrams) == 2
        assert diagrams[0][0] == "JTAG"
        assert diagrams[1][0] == "UART"

    def test_generate_all_empty(self):
        result = _make_result()
        diagrams = generate_all_pinout_svgs(result, [])
        assert diagrams == []

    def test_generate_all_no_debug_findings(self):
        result = _make_result()
        findings = [{"type": "other", "severity": "low"}]
        diagrams = generate_all_pinout_svgs(result, findings)
        assert diagrams == []


class TestSaveToDisk:
    def test_save_creates_file(self, tmp_path):
        result = _make_result()
        finding = _make_finding()
        out = tmp_path / "pinout.svg"
        save_pinout_svg(result, finding, str(out))
        assert out.exists()
        content = out.read_text()
        assert "<svg" in content
        assert "JTAG" in content

    def test_save_creates_parent_dirs(self, tmp_path):
        result = _make_result()
        finding = _make_finding()
        out = tmp_path / "sub" / "dir" / "pinout.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        save_pinout_svg(result, finding, str(out))
        assert out.exists()
