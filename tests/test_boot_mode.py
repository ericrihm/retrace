"""Tests for boot mode pin detection plugin."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component
from retrace.plugins.builtin.boot_mode import (
    BootModeAnalyzer,
    detect_boot_mode_pins,
)


def _comp(id: str, label: str = "ic", marking: str = "", part_number: str = "",
          bbox: tuple[int, int, int, int] = (0, 0, 20, 20)) -> Component:
    return Component(
        id=id, label=label, confidence=0.9, bbox=bbox,
        marking=marking, part_number=part_number,
    )


def _board(*comps: Component) -> AnalysisResult:
    return AnalysisResult(image_path="/fake/board.jpg", components=list(comps))


# ---------------------------------------------------------------------------
# MCU family detection
# ---------------------------------------------------------------------------

class TestFamilyDetection:
    def test_stm32_detected(self):
        mcu = _comp("U1", marking="STM32F103C8T6")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1
        assert "STM32" in findings[0]["description"]

    def test_esp32_detected(self):
        mcu = _comp("U1", marking="ESP32-WROOM-32")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1
        assert "ESP32" in findings[0]["description"]

    def test_nrf52_detected(self):
        mcu = _comp("U1", marking="nRF52840")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_pic_detected(self):
        mcu = _comp("U1", marking="PIC18F4520")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_avr_detected(self):
        mcu = _comp("U1", marking="ATmega328P")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_rp2040_detected(self):
        mcu = _comp("U1", marking="RP2040")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1
        assert findings[0]["severity"] == "medium"

    def test_samd_detected(self):
        mcu = _comp("U1", marking="SAMD21G18A")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_lpc_detected(self):
        mcu = _comp("U1", marking="LPC1768")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_efm32_detected(self):
        mcu = _comp("U1", marking="EFM32GG990")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_unknown_ic_not_detected(self):
        ic = _comp("U1", marking="MAX7219")
        findings = detect_boot_mode_pins(_board(ic))
        assert len(findings) == 0

    def test_resistor_not_detected(self):
        r = _comp("R1", label="resistor", marking="10K")
        findings = detect_boot_mode_pins(_board(r))
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# Accessible pin detection
# ---------------------------------------------------------------------------

class TestAccessiblePins:
    def test_boot0_test_point_found(self):
        mcu = _comp("U1", marking="STM32F103")
        tp = _comp("TP1", label="test_point", marking="BOOT0")
        findings = detect_boot_mode_pins(_board(mcu, tp))
        assert findings[0]["accessible_pins"] == ["BOOT0"]

    def test_gpio0_header_found(self):
        mcu = _comp("U1", marking="ESP32-S3")
        hdr = _comp("J1", label="header", marking="GPIO0")
        findings = detect_boot_mode_pins(_board(mcu, hdr))
        assert "GPIO0" in findings[0]["accessible_pins"]

    def test_no_test_points_no_accessible(self):
        mcu = _comp("U1", marking="STM32F103")
        findings = detect_boot_mode_pins(_board(mcu))
        assert findings[0]["accessible_pins"] == []

    def test_unrelated_test_point_ignored(self):
        mcu = _comp("U1", marking="STM32F103")
        tp = _comp("TP1", label="test_point", marking="VCC")
        findings = detect_boot_mode_pins(_board(mcu, tp))
        assert findings[0]["accessible_pins"] == []

    def test_multiple_accessible_pins(self):
        mcu = _comp("U1", marking="ATmega328P")
        tp1 = _comp("TP1", label="test_point", marking="RESET")
        tp2 = _comp("TP2", label="test_point", marking="MOSI")
        tp3 = _comp("TP3", label="test_point", marking="MISO")
        findings = detect_boot_mode_pins(_board(mcu, tp1, tp2, tp3))
        accessible = findings[0]["accessible_pins"]
        assert "RESET" in accessible
        assert "MOSI" in accessible
        assert "MISO" in accessible


# ---------------------------------------------------------------------------
# CVSS scoring
# ---------------------------------------------------------------------------

class TestCVSSScoring:
    def test_accessible_pins_higher_cvss(self):
        mcu = _comp("U1", marking="STM32F103")
        tp = _comp("TP1", label="test_point", marking="BOOT0")
        findings = detect_boot_mode_pins(_board(mcu, tp))
        assert findings[0]["cvss_base"] == 7.6

    def test_no_accessible_pins_lower_cvss(self):
        mcu = _comp("U1", marking="STM32F103")
        findings = detect_boot_mode_pins(_board(mcu))
        assert findings[0]["cvss_base"] == 4.6


# ---------------------------------------------------------------------------
# Finding fields
# ---------------------------------------------------------------------------

class TestFindingFields:
    def test_has_extraction_tool(self):
        mcu = _comp("U1", marking="ESP32-S3")
        findings = detect_boot_mode_pins(_board(mcu))
        assert "esptool" in findings[0]["extraction_tool"]

    def test_has_bootloader_protocol(self):
        mcu = _comp("U1", marking="STM32F103")
        findings = detect_boot_mode_pins(_board(mcu))
        assert "UART" in findings[0]["bootloader_protocol"]

    def test_has_boot_pins_list(self):
        mcu = _comp("U1", marking="RP2040")
        findings = detect_boot_mode_pins(_board(mcu))
        assert "BOOTSEL" in findings[0]["boot_pins"]

    def test_has_cve_reference(self):
        mcu = _comp("U1", marking="STM32F103")
        findings = detect_boot_mode_pins(_board(mcu))
        assert findings[0]["cve_reference"] == "CWE-1191"

    def test_has_mitre_attack(self):
        mcu = _comp("U1", marking="STM32F103")
        findings = detect_boot_mode_pins(_board(mcu))
        assert "T1200" in findings[0]["mitre_attack"]


# ---------------------------------------------------------------------------
# Analyzer class
# ---------------------------------------------------------------------------

class TestBootModeAnalyzer:
    def test_name(self):
        assert BootModeAnalyzer.name == "boot_mode"

    def test_analyze_returns_required_keys(self):
        mcu = _comp("U1", marking="STM32F103")
        result = BootModeAnalyzer().analyze(_board(mcu))
        assert "findings" in result
        assert "summary" in result
        assert "plugin" in result

    def test_analyze_empty_board(self):
        result = BootModeAnalyzer().analyze(_board())
        assert result["findings"] == []
        assert "0 MCU" in result["summary"]

    def test_summary_counts_accessible(self):
        mcu = _comp("U1", marking="STM32F103")
        tp = _comp("TP1", label="test_point", marking="BOOT0")
        result = BootModeAnalyzer().analyze(_board(mcu, tp))
        assert "1 with accessible" in result["summary"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_board(self):
        assert detect_boot_mode_pins(_board()) == []

    def test_multiple_mcus(self):
        stm = _comp("U1", marking="STM32F103")
        esp = _comp("U2", marking="ESP32-S3")
        findings = detect_boot_mode_pins(_board(stm, esp))
        assert len(findings) == 2

    def test_part_number_match(self):
        mcu = _comp("U1", marking="", part_number="STM32F103C8T6")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1

    def test_case_insensitive(self):
        mcu = _comp("U1", marking="stm32f405rgt6")
        findings = detect_boot_mode_pins(_board(mcu))
        assert len(findings) == 1
