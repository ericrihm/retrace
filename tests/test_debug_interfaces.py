"""Tests for the debug interface detection plugin."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component
from retrace.plugins.builtin.debug_interfaces import (
    DebugInterfaceAnalyzer,
    detect_debug_interfaces,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _board_with_markings(*markings: str) -> AnalysisResult:
    components = [
        Component(
            id=f"C{i:04d}",
            label="header",
            confidence=0.9,
            bbox=(i * 30, 0, 20, 10),
            marking=m,
        )
        for i, m in enumerate(markings)
    ]
    return AnalysisResult(image_path="/fake/board.jpg", components=components)


def _board_with_labels(*labels: str) -> AnalysisResult:
    components = [
        Component(
            id=f"C{i:04d}",
            label=lbl,
            confidence=0.9,
            bbox=(i * 30, 0, 20, 10),
        )
        for i, lbl in enumerate(labels)
    ]
    return AnalysisResult(image_path="/fake/board.jpg", components=components)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_detect_jtag_by_marking():
    board = _board_with_markings("JTAG", "some_other")
    findings = detect_debug_interfaces(board)
    ifaces = {f["interface"] for f in findings}
    assert "JTAG" in ifaces


def test_detect_uart_by_marking():
    board = _board_with_markings("UART_DEBUG", "GND", "VCC")
    findings = detect_debug_interfaces(board)
    ifaces = {f["interface"] for f in findings}
    assert "UART" in ifaces


def test_no_findings_for_clean_board():
    board = _board_with_markings("R1", "C1", "D1")
    findings = detect_debug_interfaces(board)
    assert findings == []


def test_debug_interface_analyzer_plugin_api():
    """DebugInterfaceAnalyzer.analyze() must return expected keys."""
    board = _board_with_markings("SWD_CLK", "TDI", "GND")
    analyzer = DebugInterfaceAnalyzer()
    result = analyzer.analyze(board)
    assert "findings" in result
    assert "summary" in result
    assert isinstance(result["findings"], list)


def test_severity_high_for_jtag():
    board = _board_with_markings("JTAG20")
    findings = detect_debug_interfaces(board)
    jtag = next((f for f in findings if f["interface"] == "JTAG"), None)
    assert jtag is not None
    assert jtag["severity"] == "high"


def test_each_interface_detected_once():
    """Multiple JTAG markers should still produce exactly one JTAG finding."""
    board = _board_with_markings("JTAG", "TDI", "TDO", "TCK")
    findings = detect_debug_interfaces(board)
    jtag_findings = [f for f in findings if f["interface"] == "JTAG"]
    assert len(jtag_findings) == 1


def test_cvss_score_present():
    board = _board_with_markings("JTAG")
    findings = detect_debug_interfaces(board)
    jtag = next(f for f in findings if f["interface"] == "JTAG")
    assert jtag["cvss_base"] == 7.6
    assert jtag["cvss_vector"].startswith("CVSS:3.1/")


def test_mitre_attack_present():
    board = _board_with_markings("JTAG")
    findings = detect_debug_interfaces(board)
    jtag = next(f for f in findings if f["interface"] == "JTAG")
    assert "T1200" in jtag["mitre_attack"]
    assert "T0839" in jtag["mitre_attack"]


def test_uart_cvss_medium():
    board = _board_with_markings("CONSOLE")
    findings = detect_debug_interfaces(board)
    uart = next(f for f in findings if f["interface"] == "UART")
    assert uart["cvss_base"] == 6.8


def test_i2c_low_severity_with_cvss():
    board = _board_with_markings("I2C_BUS")
    findings = detect_debug_interfaces(board)
    i2c = next(f for f in findings if f["interface"] == "I2C")
    assert i2c["severity"] == "low"
    assert i2c["cvss_base"] == 3.5
    assert i2c["mitre_attack"] == ["T1200"]
