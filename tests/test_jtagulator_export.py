"""Tests for JTAGulator config export module."""

from __future__ import annotations

from retrace.export.jtagulator import (
    _extract_signal_pins,
    _get_pinout_for_finding,
    _jtag_signal_pins,
    _swd_signal_pins,
    _uart_signal_pins,
    export_jtagulator_configs,
    generate_jtagulator_config,
    generate_openocd_config,
)

# ---------------------------------------------------------------------------
# Test finding factories
# ---------------------------------------------------------------------------

def _jtag_finding(**overrides) -> dict:
    base = {
        "type": "debug_interface",
        "interface": "JTAG",
        "severity": "high",
        "description": "JTAG debug interface — full CPU debug/program access",
        "component_id": "J5",
        "component_label": "header",
        "component_marking": "JTAG20",
        "cve_reference": "CWE-1191",
        "cvss_base": 7.6,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "mitre_attack": ["T1200", "T0839"],
    }
    base.update(overrides)
    return base


def _uart_finding(**overrides) -> dict:
    base = {
        "type": "debug_interface",
        "interface": "UART",
        "severity": "medium",
        "description": "UART/serial console — may expose bootloader or root shell",
        "component_id": "J3",
        "component_label": "connector",
        "component_marking": "UART",
        "cve_reference": "CWE-1299",
        "cvss_base": 6.8,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "mitre_attack": ["T1200"],
    }
    base.update(overrides)
    return base


def _swd_finding(**overrides) -> dict:
    base = {
        "type": "debug_interface",
        "interface": "SWD",
        "severity": "high",
        "description": "ARM Serial Wire Debug — CoreSight access, firmware extraction risk",
        "component_id": "J2",
        "component_label": "header",
        "component_marking": "SWD",
        "cve_reference": "CWE-1191",
        "cvss_base": 7.6,
        "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "mitre_attack": ["T1200", "T0839"],
    }
    base.update(overrides)
    return base


def _spi_finding(**overrides) -> dict:
    base = {
        "type": "debug_interface",
        "interface": "SPI",
        "severity": "medium",
        "description": "SPI interface — potential flash memory read/write access",
        "component_id": "U2",
        "component_label": "ic",
        "component_marking": "W25Q128",
        "cve_reference": None,
        "cvss_base": 5.3,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pin extraction tests
# ---------------------------------------------------------------------------

class TestJtagSignalPins:
    def test_20pin_jtag_has_all_signals(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["JTAG"][20]
        sig = _jtag_signal_pins(pins)
        assert sig["TDI"] is not None
        assert sig["TDO"] is not None
        assert sig["TCK"] is not None
        assert sig["TMS"] is not None
        # nTRST should map to TRST
        assert sig["TRST"] is not None

    def test_10pin_jtag_has_core_signals(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["JTAG"][10]
        sig = _jtag_signal_pins(pins)
        assert sig["TDI"] is not None
        assert sig["TCK"] is not None
        assert sig["TMS"] is not None

    def test_returns_none_for_missing_signal(self):
        # Minimal pin list with no TRST
        pins = [("TDI", "data", "d"), ("TDO", "data", "d"), ("TCK", "clock", "c")]
        sig = _jtag_signal_pins(pins)
        assert sig["TRST"] is None


class TestSwdSignalPins:
    def test_10pin_swd(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["SWD"][10]
        sig = _swd_signal_pins(pins)
        assert sig["SWDIO"] is not None
        assert sig["SWCLK"] is not None
        assert sig["SWO"] is not None
        assert sig["RESET"] is not None

    def test_4pin_swd(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["SWD"][4]
        sig = _swd_signal_pins(pins)
        assert sig["SWCLK"] is not None
        assert sig["SWDIO"] is not None

    def test_2pin_minimal(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["SWD"][2]
        sig = _swd_signal_pins(pins)
        assert sig["SWCLK"] is not None
        assert sig["SWDIO"] is not None
        # No SWO or RESET on 2-pin
        assert sig["SWO"] is None
        assert sig["RESET"] is None


class TestUartSignalPins:
    def test_4pin_uart(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["UART"][4]
        sig = _uart_signal_pins(pins)
        assert sig["TX"] is not None
        assert sig["RX"] is not None
        assert sig["GND"] is not None

    def test_3pin_uart(self):
        from retrace.export.pinout_diagram import _PINOUTS

        pins = _PINOUTS["UART"][3]
        sig = _uart_signal_pins(pins)
        assert sig["TX"] is not None
        assert sig["RX"] is not None
        assert sig["GND"] is not None


class TestExtractSignalPins:
    def test_groups_by_signal_name(self):
        pins = [
            ("TDI", "data", "Test data in"),
            ("GND", "ground", "Ground"),
            ("TDO", "data", "Test data out"),
        ]
        signals = _extract_signal_pins("JTAG", pins)
        assert "TDI" in signals
        assert "GND" in signals
        assert "TDO" in signals
        assert signals["TDI"][0]["pin_number"] == 1

    def test_split_signal_uses_first_part(self):
        pins = [("TMS/SWDIO", "control", "Test mode / SWD data")]
        signals = _extract_signal_pins("JTAG", pins)
        assert "TMS" in signals


# ---------------------------------------------------------------------------
# JTAGulator config output tests
# ---------------------------------------------------------------------------

class TestGenerateJtagulatorConfig:
    def test_empty_findings_produces_no_interface_message(self):
        config = generate_jtagulator_config([], board_name="test_board")
        assert "No debug interfaces detected" in config
        assert "test_board" in config

    def test_jtag_finding_produces_jtag_section(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "JTAG Interface" in config
        assert "IDCODE scan" in config
        assert "BYPASS scan" in config
        assert "J " in config or "J " in config.replace("#   ", "")

    def test_uart_finding_produces_uart_section(self):
        config = generate_jtagulator_config([_uart_finding()])
        assert "UART" in config
        assert "passthrough" in config.lower() or "U " in config
        assert "115200" in config
        assert "baud" in config.lower()

    def test_swd_finding_produces_swd_section(self):
        config = generate_jtagulator_config([_swd_finding()])
        assert "SWD" in config
        assert "SWDIO" in config
        assert "SWCLK" in config

    def test_voltage_warning_present(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "voltage" in config.lower()
        assert "3.3" in config

    def test_custom_voltage(self):
        config = generate_jtagulator_config([_jtag_finding()], voltage="1.8")
        assert "1.8" in config

    def test_custom_board_name(self):
        config = generate_jtagulator_config(
            [_jtag_finding()], board_name="Neptune Apex",
        )
        assert "Neptune Apex" in config

    def test_cvss_score_in_output(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "7.6" in config

    def test_cwe_reference_in_output(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "CWE-1191" in config

    def test_multiple_interfaces(self):
        findings = [_jtag_finding(), _uart_finding(), _swd_finding()]
        config = generate_jtagulator_config(findings)
        assert "JTAG Interface" in config
        assert "UART" in config
        assert "SWD" in config

    def test_spi_section_mentions_flashrom(self):
        config = generate_jtagulator_config([_spi_finding()])
        assert "flashrom" in config

    def test_pin_numbers_in_jtag_config(self):
        config = generate_jtagulator_config([_jtag_finding()])
        # Should have pin number assignments
        assert "Pin" in config
        assert "TDI" in config
        assert "TDO" in config
        assert "TCK" in config
        assert "TMS" in config

    def test_channel_assignments_in_jtag(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "CH0" in config

    def test_ends_with_newline(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert config.endswith("\n")

    def test_header_and_footer(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "============" in config
        assert "re:trace" in config
        assert "End of JTAGulator" in config

    def test_uart_baud_rates_listed(self):
        config = generate_jtagulator_config([_uart_finding()])
        assert "9600" in config
        assert "115200" in config
        assert "921600" in config
        assert "most common" in config

    def test_uart_tx_rx_crossover_note(self):
        config = generate_jtagulator_config([_uart_finding()])
        assert "target TX -> adapter RX" in config or "TX/RX" in config


# ---------------------------------------------------------------------------
# OpenOCD config tests
# ---------------------------------------------------------------------------

class TestGenerateOpenocdConfig:
    def test_empty_findings_produces_empty(self):
        config = generate_openocd_config([])
        assert config == ""

    def test_jtag_produces_openocd(self):
        config = generate_openocd_config([_jtag_finding()])
        assert "transport select jtag" in config
        assert "adapter speed" in config
        assert "interface" in config.lower()
        assert "scan_chain" in config

    def test_swd_produces_openocd(self):
        config = generate_openocd_config([_swd_finding()])
        assert "transport select swd" in config
        assert "adapter speed" in config

    def test_uart_does_not_produce_openocd(self):
        config = generate_openocd_config([_uart_finding()])
        assert config.strip() == ""

    def test_spi_does_not_produce_openocd(self):
        config = generate_openocd_config([_spi_finding()])
        assert config.strip() == ""

    def test_openocd_has_reset_config(self):
        config = generate_openocd_config([_jtag_finding()])
        assert "reset_config" in config

    def test_openocd_board_name_in_comments(self):
        config = generate_openocd_config(
            [_jtag_finding()], board_name="MyBoard",
        )
        assert "MyBoard" not in config  # board_name goes in component ref, not top-level
        # But the component ref should be there
        assert "header" in config

    def test_mixed_findings_only_jtag_swd(self):
        findings = [_jtag_finding(), _uart_finding(), _swd_finding()]
        config = generate_openocd_config(findings)
        assert "transport select jtag" in config
        assert "transport select swd" in config
        # UART should not contribute
        assert config.count("source [find interface/") == 2


# ---------------------------------------------------------------------------
# Combined export tests
# ---------------------------------------------------------------------------

class TestExportJtagulatorConfigs:
    def test_jtag_produces_both_files(self):
        result = export_jtagulator_configs([_jtag_finding()])
        assert "jtagulator.txt" in result
        assert "openocd.cfg" in result

    def test_uart_only_produces_jtagulator_txt(self):
        result = export_jtagulator_configs([_uart_finding()])
        assert "jtagulator.txt" in result
        assert "openocd.cfg" not in result

    def test_empty_findings_produces_jtagulator_txt(self):
        result = export_jtagulator_configs([])
        assert "jtagulator.txt" in result
        assert "No debug interfaces detected" in result["jtagulator.txt"]

    def test_voltage_passed_through(self):
        result = export_jtagulator_configs([_jtag_finding()], voltage="5.0")
        assert "5.0" in result["jtagulator.txt"]

    def test_board_name_passed_through(self):
        result = export_jtagulator_configs(
            [_jtag_finding()], board_name="TestBoard",
        )
        assert "TestBoard" in result["jtagulator.txt"]


# ---------------------------------------------------------------------------
# Pinout resolution tests
# ---------------------------------------------------------------------------

class TestGetPinoutForFinding:
    def test_jtag_finding_returns_pins(self):
        pins = _get_pinout_for_finding(_jtag_finding())
        assert len(pins) > 0
        names = [p[0] for p in pins]
        assert "TDI" in names

    def test_swd_finding_returns_pins(self):
        pins = _get_pinout_for_finding(_swd_finding())
        assert len(pins) > 0
        names = [p[0] for p in pins]
        assert "SWDIO" in names

    def test_uart_finding_returns_pins(self):
        pins = _get_pinout_for_finding(_uart_finding())
        assert len(pins) > 0
        names = [p[0] for p in pins]
        assert "TX" in names
        assert "RX" in names

    def test_unknown_interface_returns_empty(self):
        finding = _jtag_finding(interface="UNKNOWN_BUS")
        pins = _get_pinout_for_finding(finding)
        assert pins == []


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_finding_with_no_component_label(self):
        finding = _jtag_finding(component_label="", component_marking="")
        config = generate_jtagulator_config([finding])
        # Should not crash, should still produce valid output
        assert "JTAG Interface" in config

    def test_finding_with_no_cvss(self):
        finding = _jtag_finding(cvss_base=None, cvss_vector=None)
        config = generate_jtagulator_config([finding])
        assert "JTAG Interface" in config
        # Should not have "CVSS None"
        assert "CVSS None" not in config

    def test_finding_with_no_cve(self):
        finding = _jtag_finding(cve_reference=None)
        config = generate_jtagulator_config([finding])
        assert "JTAG Interface" in config
        assert "CWE: None" not in config

    def test_i2c_finding(self):
        finding = {
            "type": "debug_interface",
            "interface": "I2C",
            "severity": "low",
            "description": "I2C bus",
            "component_id": "J1",
            "component_label": "header",
            "component_marking": "I2C",
            "cve_reference": None,
            "cvss_base": 3.5,
        }
        config = generate_jtagulator_config([finding])
        assert "I2C" in config
        assert "i2cdetect" in config

    def test_safety_warnings_always_present(self):
        for finding_fn in (_jtag_finding, _uart_finding, _swd_finding, _spi_finding):
            config = generate_jtagulator_config([finding_fn()])
            assert "SAFETY" in config or "voltage" in config.lower()
            assert "GND" in config

    def test_quick_start_guide_present(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "QUICK START" in config

    def test_openocd_follow_up_in_jtag(self):
        config = generate_jtagulator_config([_jtag_finding()])
        assert "openocd" in config.lower()

    def test_screen_minicom_in_uart(self):
        config = generate_jtagulator_config([_uart_finding()])
        assert "screen" in config or "minicom" in config or "picocom" in config
