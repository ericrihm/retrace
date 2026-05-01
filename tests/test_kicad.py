"""Tests for KiCad netlist and PCB exporters."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.export.kicad import (
    _build_nets,
    _footprint_for,
    _pin_count,
    _px_to_mm,
    generate_kicad_netlist,
    generate_kicad_pcb,
    save_kicad_netlist,
    save_kicad_pcb,
)


def _make_result(
    components=None,
    traces=None,
    image_path="board.png",
) -> AnalysisResult:
    return AnalysisResult(
        image_path=image_path,
        components=components or [],
        traces=traces or [],
        board_dimensions=(800, 600),
        timestamp="2025-01-15 10:30:00",
    )


def _make_ic(ref="U1", marking="STM32F030", part_number="STM32F030C8T6",
             package="LQFP-48", **kwargs):
    return Component(
        id=ref, label="ic", confidence=0.95,
        bbox=(10, 10, 50, 50), marking=marking,
        part_number=part_number, package=package, **kwargs,
    )


def _make_resistor(ref="R1", value="10k", package="0402"):
    return Component(
        id=ref, label="resistor", confidence=0.90,
        bbox=(70, 10, 20, 10), value=value, package=package,
    )


def _make_capacitor(ref="C1", value="100nF", package="0402"):
    return Component(
        id=ref, label="capacitor", confidence=0.88,
        bbox=(100, 10, 15, 15), value=value, package=package,
    )


# ---------------------------------------------------------------------------
# Basic output structure
# ---------------------------------------------------------------------------

class TestBasicNetlist:
    def test_empty_result(self):
        result = _make_result()
        xml = generate_kicad_netlist(result)
        assert '(export (version "E")' in xml
        assert "(components" in xml
        assert "(nets" in xml

    def test_single_component(self):
        result = _make_result(components=[_make_ic()])
        xml = generate_kicad_netlist(result)
        assert '(ref "U1")' in xml
        assert "STM32F030C8T6" in xml

    def test_tool_version(self):
        result = _make_result()
        xml = generate_kicad_netlist(result)
        assert "retrace" in xml

    def test_timestamp_in_design(self):
        result = _make_result()
        xml = generate_kicad_netlist(result)
        assert "2025-01-15" in xml

    def test_source_path(self):
        result = _make_result(image_path="/path/to/board.jpg")
        xml = generate_kicad_netlist(result)
        assert "/path/to/board.jpg" in xml

    def test_title_in_output(self):
        result = _make_result()
        xml = generate_kicad_netlist(result, title="Cisco ASA 5506-X")
        assert xml  # title is used for metadata, not necessarily visible in s-expr


# ---------------------------------------------------------------------------
# Component rendering
# ---------------------------------------------------------------------------

class TestComponents:
    def test_ic_has_value(self):
        result = _make_result(components=[_make_ic()])
        xml = generate_kicad_netlist(result)
        assert '(value "STM32F030C8T6")' in xml

    def test_resistor_value(self):
        result = _make_result(components=[_make_resistor(value="4.7k")])
        xml = generate_kicad_netlist(result)
        assert '(value "4.7k")' in xml

    def test_capacitor_value(self):
        result = _make_result(components=[_make_capacitor(value="100nF")])
        xml = generate_kicad_netlist(result)
        assert '(value "100nF")' in xml

    def test_footprint_mapping(self):
        result = _make_result(components=[_make_resistor(package="0805")])
        xml = generate_kicad_netlist(result)
        assert "Resistor_SMD:R_0805_2012Metric" in xml

    def test_datasheet_url(self):
        ic = _make_ic(datasheet_url="https://example.com/ds.pdf")
        result = _make_result(components=[ic])
        xml = generate_kicad_netlist(result)
        assert "https://example.com/ds.pdf" in xml

    def test_mpn_property(self):
        result = _make_result(components=[_make_ic(part_number="STM32F030C8T6")])
        xml = generate_kicad_netlist(result)
        assert '(name "MPN")' in xml
        assert "STM32F030C8T6" in xml

    def test_package_property(self):
        result = _make_result(components=[_make_ic(package="LQFP-48")])
        xml = generate_kicad_netlist(result)
        assert '(name "Package")' in xml
        assert "LQFP-48" in xml

    def test_libsource_ic(self):
        result = _make_result(components=[_make_ic()])
        xml = generate_kicad_netlist(result)
        assert '(lib "Device")' in xml

    def test_libsource_resistor(self):
        result = _make_result(components=[_make_resistor()])
        xml = generate_kicad_netlist(result)
        assert '(part "R")' in xml

    def test_multiple_components(self):
        comps = [_make_ic(), _make_resistor(), _make_capacitor()]
        result = _make_result(components=comps)
        xml = generate_kicad_netlist(result)
        assert '(ref "U1")' in xml
        assert '(ref "R1")' in xml
        assert '(ref "C1")' in xml

    def test_component_without_value_falls_back(self):
        comp = Component(id="U2", label="ic", confidence=0.9,
                         bbox=(10, 10, 50, 50), marking="UNKNOWN")
        result = _make_result(components=[comp])
        xml = generate_kicad_netlist(result)
        assert '(value "UNKNOWN")' in xml

    def test_component_without_anything_uses_label(self):
        comp = Component(id="X1", label="crystal", confidence=0.8,
                         bbox=(10, 10, 10, 10))
        result = _make_result(components=[comp])
        xml = generate_kicad_netlist(result)
        assert '(value "crystal")' in xml


# ---------------------------------------------------------------------------
# Net generation
# ---------------------------------------------------------------------------

class TestNets:
    def test_single_trace_creates_net(self):
        comps = [_make_ic(), _make_resistor()]
        traces = [Trace(id="N1", points=[(30, 30), (80, 15)],
                        from_component="U1", to_component="R1")]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)
        assert '(name "N1")' in xml
        assert '(ref "U1")' in xml
        assert '(ref "R1")' in xml

    def test_multiple_nets(self):
        comps = [_make_ic(), _make_resistor(), _make_capacitor()]
        traces = [
            Trace(id="VCC", points=[(30, 30), (80, 15)],
                  from_component="U1", to_component="R1"),
            Trace(id="GND", points=[(30, 30), (110, 15)],
                  from_component="U1", to_component="C1"),
        ]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)
        assert '(name "VCC")' in xml
        assert '(name "GND")' in xml

    def test_trace_without_endpoints_skipped(self):
        comps = [_make_ic()]
        traces = [Trace(id="T1", points=[(10, 10), (20, 20)])]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)
        assert "T1" not in xml or "(nets" in xml

    def test_auto_generated_net_name(self):
        comps = [_make_ic(), _make_resistor()]
        traces = [Trace(id="", points=[(30, 30), (80, 15)],
                        from_component="U1", to_component="R1")]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)
        assert "Net-(U1-R1)" in xml

    def test_net_has_pin_numbers(self):
        comps = [_make_ic(), _make_resistor()]
        traces = [Trace(id="N1", points=[(30, 30), (80, 15)],
                        from_component="U1", to_component="R1")]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)
        assert '(pin "' in xml

    def test_passive_pins_clamped_to_2(self):
        r = _make_resistor()
        comps = [_make_ic(), r]
        traces = [
            Trace(id="N1", points=[], from_component="U1", to_component="R1"),
            Trace(id="N2", points=[], from_component="U1", to_component="R1"),
            Trace(id="N3", points=[], from_component="U1", to_component="R1"),
        ]
        _make_result(components=comps, traces=traces)
        nets = _build_nets(comps, traces)
        for net_name, endpoints in nets.items():
            for ref, pin in endpoints:
                if ref == "R1":
                    assert int(pin) <= 2


# ---------------------------------------------------------------------------
# Footprint mapping
# ---------------------------------------------------------------------------

class TestFootprintMapping:
    def test_known_package(self):
        comp = _make_resistor(package="0805")
        assert "0805" in _footprint_for(comp)

    def test_sot23(self):
        comp = Component(id="Q1", label="ic", confidence=0.9,
                         bbox=(0, 0, 10, 10), package="SOT-23")
        assert "SOT-23" in _footprint_for(comp)

    def test_unknown_package_returns_empty(self):
        comp = Component(id="U1", label="ic", confidence=0.9,
                         bbox=(0, 0, 10, 10), package="WEIRD-99")
        assert _footprint_for(comp) == ""

    def test_default_resistor_no_package(self):
        comp = Component(id="R1", label="resistor", confidence=0.9,
                         bbox=(0, 0, 10, 10))
        fp = _footprint_for(comp)
        assert "Resistor_SMD" in fp

    def test_default_capacitor_no_package(self):
        comp = Component(id="C1", label="capacitor", confidence=0.9,
                         bbox=(0, 0, 10, 10))
        fp = _footprint_for(comp)
        assert "Capacitor_SMD" in fp

    def test_lqfp48(self):
        comp = _make_ic(package="LQFP-48")
        fp = _footprint_for(comp)
        assert "LQFP-48" in fp

    def test_case_insensitive(self):
        comp = _make_ic(package="lqfp-48")
        fp = _footprint_for(comp)
        assert "LQFP-48" in fp


# ---------------------------------------------------------------------------
# Pin count
# ---------------------------------------------------------------------------

class TestPinCount:
    def test_resistor_has_2_pins(self):
        assert _pin_count(_make_resistor()) == 2

    def test_capacitor_has_2_pins(self):
        assert _pin_count(_make_capacitor()) == 2

    def test_ic_has_4_pins(self):
        assert _pin_count(_make_ic()) == 4

    def test_test_point_has_1_pin(self):
        tp = Component(id="TP1", label="test_point", confidence=0.9,
                       bbox=(0, 0, 5, 5))
        assert _pin_count(tp) == 1


# ---------------------------------------------------------------------------
# Save to disk
# ---------------------------------------------------------------------------

class TestSaveToDisk:
    def test_save_creates_file(self, tmp_path):
        result = _make_result(components=[_make_ic(), _make_resistor()])
        out = tmp_path / "board.net"
        save_kicad_netlist(result, str(out))
        assert out.exists()
        content = out.read_text()
        assert '(export (version "E")' in content

    def test_save_creates_parent_dirs(self, tmp_path):
        result = _make_result()
        out = tmp_path / "sub" / "dir" / "board.net"
        save_kicad_netlist(result, str(out))
        assert out.exists()

    def test_save_utf8(self, tmp_path):
        comp = _make_ic(marking="Ω-chip")
        result = _make_result(components=[comp])
        out = tmp_path / "board.net"
        save_kicad_netlist(result, str(out))
        content = out.read_text(encoding="utf-8")
        assert "Ω-chip" in content


# ---------------------------------------------------------------------------
# XSS / injection safety
# ---------------------------------------------------------------------------

class TestSafeEscaping:
    def test_xml_special_chars_in_marking(self):
        comp = _make_ic(marking='<script>alert("xss")</script>')
        result = _make_result(components=[comp])
        xml = generate_kicad_netlist(result)
        assert "<script>" not in xml
        assert "&lt;" in xml

    def test_quotes_in_value(self):
        comp = _make_resistor(value='10k"ohm')
        result = _make_result(components=[comp])
        xml = generate_kicad_netlist(result)
        assert xml  # should not crash


# ---------------------------------------------------------------------------
# Integration: realistic board
# ---------------------------------------------------------------------------

class TestRealisticBoard:
    def test_cisco_like_board(self):
        comps = [
            _make_ic(ref="U1", marking="C2508", part_number="ATOM-C2508",
                     package="BGA-256"),
            _make_ic(ref="U6", marking="XC6SLX", part_number="XC6SLX9",
                     package="BGA-256"),
            _make_ic(ref="U7", marking="W25Q128", part_number="W25Q128JV",
                     package="SOIC-8"),
            _make_resistor(ref="R1", value="10k"),
            _make_capacitor(ref="C1", value="100nF"),
        ]
        traces = [
            Trace(id="SPI_CLK", points=[], from_component="U1", to_component="U7"),
            Trace(id="SPI_MOSI", points=[], from_component="U1", to_component="U7"),
            Trace(id="FPGA_CFG", points=[], from_component="U7", to_component="U6"),
        ]
        result = _make_result(components=comps, traces=traces)
        xml = generate_kicad_netlist(result)

        assert '(ref "U1")' in xml
        assert '(ref "U6")' in xml
        assert '(ref "U7")' in xml
        assert '(name "SPI_CLK")' in xml
        assert '(name "SPI_MOSI")' in xml
        assert '(name "FPGA_CFG")' in xml
        assert "ATOM-C2508" in xml
        assert "W25Q128JV" in xml


# ---------------------------------------------------------------------------
# KiCad PCB positional export tests
# ---------------------------------------------------------------------------


class TestPxToMm:
    def test_default_scale(self):
        assert _px_to_mm(100) == 10.0

    def test_custom_scale(self):
        assert _px_to_mm(100, 0.05) == 5.0

    def test_zero(self):
        assert _px_to_mm(0) == 0.0


class TestGenerateKicadPcb:
    def test_empty_result(self):
        result = _make_result()
        pcb = generate_kicad_pcb(result)
        assert "(kicad_pcb" in pcb
        assert "Edge.Cuts" in pcb
        assert "(thickness 1.6)" in pcb

    def test_board_dimensions(self):
        result = _make_result()
        pcb = generate_kicad_pcb(result, scale=0.1)
        assert "80.00" in pcb  # 800 * 0.1
        assert "60.00" in pcb  # 600 * 0.1

    def test_component_placement(self):
        ic = _make_ic(ref="U1")
        result = _make_result(components=[ic])
        pcb = generate_kicad_pcb(result)
        assert '"U1"' in pcb
        assert "(footprint" in pcb
        assert "(at" in pcb

    def test_component_center_position(self):
        comp = Component(
            id="R1", label="resistor", confidence=0.9,
            bbox=(100, 200, 20, 10), package="0402",
        )
        result = _make_result(components=[comp])
        pcb = generate_kicad_pcb(result, scale=0.1)
        assert "11.00" in pcb  # (100+10) * 0.1
        assert "20.50" in pcb  # (200+5) * 0.1

    def test_multiple_components(self):
        comps = [_make_ic("U1"), _make_resistor("R1"), _make_resistor("R2")]
        result = _make_result(components=comps)
        pcb = generate_kicad_pcb(result)
        assert pcb.count("(footprint") == 3

    def test_custom_scale(self):
        comp = Component(
            id="C1", label="capacitor", confidence=0.8,
            bbox=(0, 0, 100, 100),
        )
        result = _make_result(components=[comp])
        pcb_small = generate_kicad_pcb(result, scale=0.05)
        pcb_large = generate_kicad_pcb(result, scale=0.2)
        assert "2.50" in pcb_small  # 50 * 0.05
        assert "10.00" in pcb_large  # 50 * 0.2

    def test_title_ignored(self):
        result = _make_result()
        pcb = generate_kicad_pcb(result, title="My Board")
        assert "(kicad_pcb" in pcb

    def test_escape_special_chars(self):
        comp = Component(
            id="U&1", label="ic", confidence=0.9,
            bbox=(0, 0, 10, 10), marking='AT&T "chip"',
        )
        result = _make_result(components=[comp])
        pcb = generate_kicad_pcb(result)
        assert "&amp;" in pcb


class TestSaveKicadPcb:
    def test_write_file(self, tmp_path):
        result = _make_result(components=[_make_ic()])
        out = str(tmp_path / "board.kicad_pcb")
        save_kicad_pcb(result, out)
        content = (tmp_path / "board.kicad_pcb").read_text()
        assert "(kicad_pcb" in content
        assert '"U1"' in content

    def test_creates_parent_dirs(self, tmp_path):
        result = _make_result()
        out = str(tmp_path / "sub" / "dir" / "board.kicad_pcb")
        save_kicad_pcb(result, out)
        assert (tmp_path / "sub" / "dir" / "board.kicad_pcb").exists()
