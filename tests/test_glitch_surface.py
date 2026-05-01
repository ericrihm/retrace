"""Tests for the glitch surface detection plugin."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component
from retrace.plugins.builtin.glitch_surface import (
    GlitchSurfaceAnalyzer,
    detect_glitch_surfaces,
    _is_security_ic,
    _is_voltage_regulator,
    _is_clock_source,
    _distance,
    _PROXIMITY_PX,
)


def _comp(id: str, label: str = "ic", marking: str = "", part_number: str = "",
          bbox: tuple[int, int, int, int] = (0, 0, 20, 20), package: str = "",
          value: str = "") -> Component:
    return Component(
        id=id, label=label, confidence=0.9, bbox=bbox,
        marking=marking, part_number=part_number, package=package, value=value,
    )


def _board(*comps: Component) -> AnalysisResult:
    return AnalysisResult(image_path="/fake/board.jpg", components=list(comps))


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestIsSecurityIC:
    def test_stm32_mcu(self):
        assert _is_security_ic(_comp("U1", marking="STM32F103"))

    def test_esp32_mcu(self):
        assert _is_security_ic(_comp("U1", marking="ESP32-S3"))

    def test_tpm(self):
        assert _is_security_ic(_comp("U1", marking="SLB9670"))

    def test_atecc608(self):
        assert _is_security_ic(_comp("U1", marking="ATECC608B"))

    def test_flash(self):
        assert _is_security_ic(_comp("U1", marking="W25Q128JV"))

    def test_fpga(self):
        assert _is_security_ic(_comp("U1", marking="Spartan-6"))

    def test_nrf52(self):
        assert _is_security_ic(_comp("U1", marking="nRF52840"))

    def test_regular_resistor_not_security(self):
        assert not _is_security_ic(_comp("R1", label="resistor", marking="10K"))

    def test_capacitor_not_security(self):
        assert not _is_security_ic(_comp("C1", label="capacitor", marking="100nF"))

    def test_connector_not_security(self):
        assert not _is_security_ic(_comp("J1", label="connector", marking="USB-A"))

    def test_needs_ic_label(self):
        assert not _is_security_ic(_comp("R1", label="resistor", marking="STM32"))


class TestIsVoltageRegulator:
    def test_ldo_keyword(self):
        assert _is_voltage_regulator(_comp("U2", marking="LDO 3.3V"))

    def test_ams1117(self):
        assert _is_voltage_regulator(_comp("U2", marking="AMS1117-3.3"))

    def test_tps7a(self):
        assert _is_voltage_regulator(_comp("U2", marking="TPS7A20"))

    def test_mp1584_buck(self):
        assert _is_voltage_regulator(_comp("U2", marking="MP1584EN"))

    def test_ap2112(self):
        assert _is_voltage_regulator(_comp("U2", marking="AP2112K"))

    def test_regular_ic_not_vr(self):
        assert not _is_voltage_regulator(_comp("U1", marking="STM32F103"))

    def test_resistor_not_vr(self):
        assert not _is_voltage_regulator(_comp("R1", marking="10K"))


class TestIsClockSource:
    def test_crystal(self):
        assert _is_clock_source(_comp("Y1", label="crystal", marking="8MHz"))

    def test_oscillator_ic(self):
        assert _is_clock_source(_comp("U3", label="ic", marking="OSC 25MHz"))

    def test_tcxo(self):
        assert _is_clock_source(_comp("Y2", label="crystal", marking="TCXO 12MHz"))

    def test_regular_ic_not_clock(self):
        assert not _is_clock_source(_comp("U1", label="ic", marking="STM32F103"))

    def test_resistor_not_clock(self):
        assert not _is_clock_source(_comp("R1", label="resistor", marking="10K"))


# ---------------------------------------------------------------------------
# Distance / proximity tests
# ---------------------------------------------------------------------------

class TestDistance:
    def test_same_location(self):
        a = _comp("A", bbox=(100, 100, 20, 20))
        b = _comp("B", bbox=(100, 100, 20, 20))
        assert _distance(a, b) == 0.0

    def test_horizontal_distance(self):
        a = _comp("A", bbox=(0, 0, 20, 20))
        b = _comp("B", bbox=(100, 0, 20, 20))
        assert abs(_distance(a, b) - 100.0) < 0.01

    def test_diagonal_distance(self):
        a = _comp("A", bbox=(0, 0, 0, 0))
        b = _comp("B", bbox=(30, 40, 0, 0))
        assert abs(_distance(a, b) - 50.0) < 0.01


# ---------------------------------------------------------------------------
# Voltage glitch detection
# ---------------------------------------------------------------------------

class TestVoltageGlitch:
    def test_vr_near_mcu_detected(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 1
        assert voltage_findings[0]["severity"] == "high"
        assert "CWE-1247" in voltage_findings[0]["cve_reference"]

    def test_vr_far_from_mcu_not_detected(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(0, 0, 20, 20))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(500, 500, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 0

    def test_vr_near_tpm_detected(self):
        tpm = _comp("U1", marking="SLB9670", bbox=(100, 100, 30, 30))
        vr = _comp("U2", marking="LDO_3V3", bbox=(130, 130, 20, 20))
        findings = detect_glitch_surfaces(_board(tpm, vr))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 1

    def test_multiple_vrs_near_one_mcu(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr1 = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        vr2 = _comp("U3", marking="AP2112K-1.8", bbox=(100, 150, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr1, vr2))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 2

    def test_finding_has_distance(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(200, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        assert findings[0]["distance_px"] > 0

    def test_finding_has_remediation(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        assert "remediation" in findings[0]
        assert len(findings[0]["remediation"]) > 10


# ---------------------------------------------------------------------------
# Clock glitch detection
# ---------------------------------------------------------------------------

class TestClockGlitch:
    def test_crystal_near_mcu_detected(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        xtal = _comp("Y1", label="crystal", marking="8MHz", bbox=(140, 100, 10, 10))
        findings = detect_glitch_surfaces(_board(mcu, xtal))
        clock_findings = [f for f in findings if f["subtype"] == "clock_glitch"]
        assert len(clock_findings) == 1
        assert clock_findings[0]["severity"] == "medium"

    def test_crystal_far_from_mcu_not_detected(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(0, 0, 20, 20))
        xtal = _comp("Y1", label="crystal", marking="8MHz", bbox=(500, 500, 10, 10))
        findings = detect_glitch_surfaces(_board(mcu, xtal))
        clock_findings = [f for f in findings if f["subtype"] == "clock_glitch"]
        assert len(clock_findings) == 0

    def test_oscillator_ic_detected(self):
        mcu = _comp("U1", marking="ESP32-S3", bbox=(100, 100, 40, 40))
        osc = _comp("U3", label="ic", marking="OSC 40MHz", bbox=(130, 130, 10, 10))
        findings = detect_glitch_surfaces(_board(mcu, osc))
        clock_findings = [f for f in findings if f["subtype"] == "clock_glitch"]
        assert len(clock_findings) == 1


# ---------------------------------------------------------------------------
# EMFI detection
# ---------------------------------------------------------------------------

class TestEMFI:
    def test_qfn_package_detected(self):
        mcu = _comp("U1", marking="STM32F103", package="QFN-48", bbox=(100, 100, 30, 30))
        findings = detect_glitch_surfaces(_board(mcu))
        emfi_findings = [f for f in findings if f["subtype"] == "emfi"]
        assert len(emfi_findings) == 1
        assert "EMFI" in emfi_findings[0]["description"]

    def test_bga_package_detected(self):
        mcu = _comp("U1", marking="nRF52840", package="BGA-73", bbox=(100, 100, 30, 30))
        findings = detect_glitch_surfaces(_board(mcu))
        emfi_findings = [f for f in findings if f["subtype"] == "emfi"]
        assert len(emfi_findings) == 1

    def test_wlcsp_package_detected(self):
        mcu = _comp("U1", marking="ATECC608B", package="WLCSP", bbox=(100, 100, 10, 10))
        findings = detect_glitch_surfaces(_board(mcu))
        emfi_findings = [f for f in findings if f["subtype"] == "emfi"]
        assert len(emfi_findings) == 1

    def test_no_package_no_emfi(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 30, 30))
        findings = detect_glitch_surfaces(_board(mcu))
        emfi_findings = [f for f in findings if f["subtype"] == "emfi"]
        assert len(emfi_findings) == 0

    def test_large_package_no_emfi(self):
        mcu = _comp("U1", marking="STM32F103", package="LQFP-144", bbox=(100, 100, 30, 30))
        findings = detect_glitch_surfaces(_board(mcu))
        emfi_findings = [f for f in findings if f["subtype"] == "emfi"]
        assert len(emfi_findings) == 0


# ---------------------------------------------------------------------------
# Analyzer class tests
# ---------------------------------------------------------------------------

class TestGlitchSurfaceAnalyzer:
    def test_name(self):
        assert GlitchSurfaceAnalyzer.name == "glitch_surface"

    def test_analyze_returns_findings_key(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        result = GlitchSurfaceAnalyzer().analyze(_board(mcu, vr))
        assert "findings" in result
        assert "summary" in result
        assert "plugin" in result

    def test_analyze_empty_board(self):
        result = GlitchSurfaceAnalyzer().analyze(_board())
        assert result["findings"] == []
        assert "0 glitch" in result["summary"]

    def test_summary_counts(self):
        mcu = _comp("U1", marking="STM32F103", package="QFN-48", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        xtal = _comp("Y1", label="crystal", marking="8MHz", bbox=(130, 130, 10, 10))
        result = GlitchSurfaceAnalyzer().analyze(_board(mcu, vr, xtal))
        assert "1 voltage" in result["summary"]
        assert "1 clock" in result["summary"]
        assert "1 EMFI" in result["summary"]

    def test_no_security_ics_no_findings(self):
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(100, 100, 20, 20))
        xtal = _comp("Y1", label="crystal", marking="8MHz", bbox=(130, 130, 10, 10))
        result = GlitchSurfaceAnalyzer().analyze(_board(vr, xtal))
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_board(self):
        assert detect_glitch_surfaces(_board()) == []

    def test_board_with_only_passives(self):
        r = _comp("R1", label="resistor", marking="10K")
        c = _comp("C1", label="capacitor", marking="100nF")
        assert detect_glitch_surfaces(_board(r, c)) == []

    def test_vr_is_not_its_own_target(self):
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(100, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(vr))
        assert len(findings) == 0

    def test_boundary_distance(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(0, 0, 20, 20))
        vr = _comp("U2", marking="AMS1117-3.3",
                    bbox=(_PROXIMITY_PX, 0, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 1

    def test_just_beyond_boundary(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(0, 0, 20, 20))
        vr = _comp("U2", marking="AMS1117-3.3",
                    bbox=(_PROXIMITY_PX + 20, 0, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        voltage_findings = [f for f in findings if f["subtype"] == "voltage_glitch"]
        assert len(voltage_findings) == 0

    def test_mitre_attack_populated(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        assert findings[0]["mitre_attack"] == ["T1200"]

    def test_cvss_vector_present(self):
        mcu = _comp("U1", marking="STM32F103", bbox=(100, 100, 40, 40))
        vr = _comp("U2", marking="AMS1117-3.3", bbox=(150, 100, 20, 20))
        findings = detect_glitch_surfaces(_board(mcu, vr))
        assert "CVSS:3.1" in findings[0]["cvss_vector"]
