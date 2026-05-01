"""Tests for protocol topology inference module."""

from __future__ import annotations

import pytest

from retrace.core.pipeline import AnalysisResult, Component, Trace
from retrace.analysis.protocol_topology import (
    BusTopology,
    _parse_ohms,
    _proximity_threshold,
    format_topology,
    infer_topology,
)


# ---------------------------------------------------------------------------
# Component / board factory helpers
# ---------------------------------------------------------------------------


def _ic(id: str, marking: str, part: str = "", x: int = 100, y: int = 100) -> Component:
    return Component(
        id=id,
        label="ic",
        confidence=0.9,
        bbox=(x, y, 50, 50),
        marking=marking,
        part_number=part,
    )


def _resistor(id: str, value: str, x: int = 100, y: int = 100) -> Component:
    return Component(
        id=id,
        label="resistor",
        confidence=0.9,
        bbox=(x, y, 20, 10),
        value=value,
        marking=value,
    )


def _connector(id: str, marking: str = "", x: int = 100, y: int = 100) -> Component:
    return Component(
        id=id,
        label="connector",
        confidence=0.9,
        bbox=(x, y, 30, 15),
        marking=marking,
    )


def _board(*components: Component, w: int = 800, h: int = 600) -> AnalysisResult:
    return AnalysisResult(
        image_path="/fake/board.jpg",
        components=list(components),
        board_dimensions=(w, h),
    )


def _far(base: int = 100) -> int:
    """Return a coordinate that is 1000 px away — always outside proximity."""
    return base + 1000


# ---------------------------------------------------------------------------
# Unit tests: _parse_ohms
# ---------------------------------------------------------------------------


class TestParseOhms:
    def test_plain_integer(self):
        assert _parse_ohms("120") is not None
        assert abs(_parse_ohms("120") - 120) < 1

    def test_eia_three_digit_code(self):
        # "121" → 12 × 10^1 = 120 Ω
        assert abs(_parse_ohms("121") - 120) < 1

    def test_k_suffix(self):
        assert abs(_parse_ohms("4.7k") - 4700) < 1
        assert abs(_parse_ohms("10k") - 10_000) < 1
        assert abs(_parse_ohms("2.2k") - 2200) < 1

    def test_k_embedded(self):
        # "4k7" style
        assert abs(_parse_ohms("4k7") - 4700) < 1

    def test_uppercase_K(self):
        assert abs(_parse_ohms("10K") - 10_000) < 1

    def test_unparseable_returns_none(self):
        assert _parse_ohms("") is None
        assert _parse_ohms("n/a") is None
        assert _parse_ohms("??") is None

    def test_zero_gives_zero(self):
        v = _parse_ohms("0")
        assert v is not None
        assert v == 0.0


# ---------------------------------------------------------------------------
# Unit tests: _proximity_threshold
# ---------------------------------------------------------------------------


class TestProximityThreshold:
    def test_small_board_clamps_to_200(self):
        # 100×100 board diagonal ~141 px; 25% = 35 px → clamped to 200
        assert _proximity_threshold((100, 100)) == 200.0

    def test_large_board_uses_fraction(self):
        # 2000×2000 board diagonal ~2828 px; 25% = 707 px
        thresh = _proximity_threshold((2000, 2000))
        assert thresh > 200


# ---------------------------------------------------------------------------
# I2C topology tests
# ---------------------------------------------------------------------------


class TestI2CTopology:
    def test_mcu_eeprom_and_pullups_detected(self):
        """MCU + EEPROM + 4.7 kΩ pull-ups → I2C bus."""
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r1 = _resistor("R1", "4.7k", x=130, y=80)
        r2 = _resistor("R2", "4.7k", x=150, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1, r2))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)

        assert i2c is not None
        assert i2c.confidence > 0.5
        assert i2c.characteristics["pull_ups_found"] is True
        assert i2c.characteristics["pull_up_count"] >= 1

    def test_pull_up_speed_standard_mode(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r1 = _resistor("R1", "10k", x=130, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None
        assert "100 kHz" in i2c.characteristics["bus_speed"]

    def test_pull_up_speed_fast_mode(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r1 = _resistor("R1", "2.2k", x=130, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None
        assert "400 kHz" in i2c.characteristics["bus_speed"]

    def test_pull_up_speed_fast_mode_plus(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r1 = _resistor("R1", "1.0k", x=130, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None
        assert "1 MHz" in i2c.characteristics["bus_speed"]

    def test_multiple_sensors_count_addressable_devices(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        s1 = _ic("U2", "BME280", x=160, y=100)
        s2 = _ic("U3", "MPU6050", x=200, y=100)
        r1 = _resistor("R1", "4.7k", x=130, y=80)

        buses = infer_topology(_board(mcu, s1, s2, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None
        assert i2c.characteristics["addressable_peripherals"] >= 2

    def test_security_notes_present(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r1 = _resistor("R1", "4.7k", x=130, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None
        assert any("authentication" in n.lower() for n in i2c.security_notes)

    def test_no_i2c_without_capable_ic(self):
        cap = Component(
            id="C1", label="capacitor", confidence=0.9, bbox=(100, 100, 20, 20)
        )
        r1 = _resistor("R1", "4.7k", x=110, y=110)
        buses = infer_topology(_board(cap, r1))
        assert all(b.protocol != "I2C" for b in buses)

    def test_security_intel_debug_interfaces_accepted(self):
        """Component with security_intel containing I2C is treated as I2C-capable."""
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        # Attach security_intel directly (as matcher would do at runtime)
        mcu.__dict__["security_intel"] = {"debug_interfaces": ["I2C", "SWD"]}
        eeprom = _ic("U2", "AT24C128", x=160, y=100)
        r1 = _resistor("R1", "4.7k", x=130, y=80)

        buses = infer_topology(_board(mcu, eeprom, r1))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        assert i2c is not None

    def test_low_confidence_without_pullup_but_two_i2c_ics(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)

        buses = infer_topology(_board(mcu, eeprom))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        # May or may not be returned depending on confidence threshold, but if
        # returned it must be low-confidence and flag missing pull-ups.
        if i2c is not None:
            assert i2c.confidence < 0.5
            assert i2c.characteristics["pull_ups_found"] is False


# ---------------------------------------------------------------------------
# SPI topology tests
# ---------------------------------------------------------------------------


class TestSPITopology:
    def test_mcu_plus_flash_detected(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        flash = _ic("U2", "W25Q128", x=160, y=100)

        buses = infer_topology(_board(mcu, flash))
        spi = next((b for b in buses if b.protocol == "SPI"), None)

        assert spi is not None
        assert spi.confidence > 0.5
        assert "U2" in spi.nodes

    def test_mx25l_also_detected(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        flash = _ic("U2", "MX25L1606E", x=160, y=100)

        buses = infer_topology(_board(mcu, flash))
        assert any(b.protocol == "SPI" for b in buses)

    def test_firmware_risk_in_security_notes(self):
        flash = _ic("U2", "W25Q128", x=100, y=100)

        buses = infer_topology(_board(flash))
        spi = next((b for b in buses if b.protocol == "SPI"), None)
        assert spi is not None
        assert any("firmware" in n.lower() for n in spi.security_notes)

    def test_multiple_flash_chips_counted(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        f1 = _ic("U2", "W25Q128", x=160, y=100)
        f2 = _ic("U3", "GD25Q64", x=200, y=100)

        buses = infer_topology(_board(mcu, f1, f2))
        spi = next((b for b in buses if b.protocol == "SPI"), None)
        assert spi is not None
        assert spi.characteristics["flash_chip_count"] == 2

    def test_no_spi_without_flash(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        buses = infer_topology(_board(mcu))
        assert all(b.protocol != "SPI" for b in buses)


# ---------------------------------------------------------------------------
# UART topology tests
# ---------------------------------------------------------------------------


class TestUARTTopology:
    def test_cp2102_detected(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        bridge = _ic("U2", "CP2102", x=160, y=100)
        conn = _connector("J1", x=220, y=100)

        buses = infer_topology(_board(mcu, bridge, conn))
        uart = next((b for b in buses if b.protocol == "UART"), None)

        assert uart is not None
        assert uart.confidence > 0.5

    def test_ch340_detected(self):
        bridge = _ic("U2", "CH340G", x=100, y=100)
        buses = infer_topology(_board(bridge))
        assert any(b.protocol == "UART" for b in buses)

    def test_ft232_detected(self):
        bridge = _ic("U2", "FT232RL", x=100, y=100)
        buses = infer_topology(_board(bridge))
        assert any(b.protocol == "UART" for b in buses)

    def test_max3232_rs232_level(self):
        shifter = _ic("U2", "MAX3232", x=100, y=100)
        buses = infer_topology(_board(shifter))
        uart = next((b for b in buses if b.protocol == "UART"), None)
        assert uart is not None
        assert "RS-232" in uart.characteristics["level_type"]

    def test_usb_uart_level_type(self):
        bridge = _ic("U2", "CP2102", x=100, y=100)
        buses = infer_topology(_board(bridge))
        uart = next((b for b in buses if b.protocol == "UART"), None)
        assert uart is not None
        assert "USB" in uart.characteristics["level_type"]

    def test_connector_proximity_marks_external_access(self):
        bridge = _ic("U2", "CP2102", x=100, y=100)
        conn = _connector("J1", x=150, y=100)

        buses = infer_topology(_board(bridge, conn))
        uart = next((b for b in buses if b.protocol == "UART"), None)
        assert uart is not None
        assert uart.characteristics["external_connector"] is True

    def test_security_note_about_shell(self):
        bridge = _ic("U2", "CP2102", x=100, y=100)
        buses = infer_topology(_board(bridge))
        uart = next((b for b in buses if b.protocol == "UART"), None)
        assert uart is not None
        assert any("shell" in n.lower() or "bootloader" in n.lower() for n in uart.security_notes)

    def test_no_uart_without_shifter(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        buses = infer_topology(_board(mcu))
        assert all(b.protocol != "UART" for b in buses)


# ---------------------------------------------------------------------------
# CAN topology tests
# ---------------------------------------------------------------------------


class TestCANTopology:
    def test_mcp2551_detected(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        txcvr = _ic("U2", "MCP2551", x=160, y=100)

        buses = infer_topology(_board(mcu, txcvr))
        can = next((b for b in buses if b.protocol == "CAN"), None)

        assert can is not None
        assert can.confidence > 0.5

    def test_tja1050_detected(self):
        txcvr = _ic("U2", "TJA1050", x=100, y=100)
        buses = infer_topology(_board(txcvr))
        assert any(b.protocol == "CAN" for b in buses)

    def test_120ohm_termination_detected(self):
        txcvr = _ic("U2", "MCP2551", x=100, y=100)
        r_term = _resistor("R1", "120", x=130, y=100)  # plain 120 Ω

        buses = infer_topology(_board(txcvr, r_term))
        can = next((b for b in buses if b.protocol == "CAN"), None)

        assert can is not None
        assert can.characteristics["termination_found"] is True

    def test_121_eia_code_termination(self):
        # 3-digit EIA "121" = 120 Ω
        txcvr = _ic("U2", "MCP2551", x=100, y=100)
        r_term = _resistor("R1", "121", x=130, y=100)

        buses = infer_topology(_board(txcvr, r_term))
        can = next((b for b in buses if b.protocol == "CAN"), None)
        assert can is not None
        assert can.characteristics["termination_found"] is True

    def test_higher_confidence_with_termination(self):
        txcvr = _ic("U2", "MCP2551", x=100, y=100)
        r_term = _resistor("R1", "120", x=130, y=100)
        txcvr_bare = _ic("U3", "MCP2551", x=500, y=100)

        buses_with = infer_topology(_board(txcvr, r_term))
        buses_without = infer_topology(_board(txcvr_bare))

        can_with = next((b for b in buses_with if b.protocol == "CAN"), None)
        can_without = next((b for b in buses_without if b.protocol == "CAN"), None)
        assert can_with is not None and can_without is not None
        assert can_with.confidence >= can_without.confidence

    def test_security_notes_mention_injection(self):
        txcvr = _ic("U2", "TJA1051", x=100, y=100)
        buses = infer_topology(_board(txcvr))
        can = next((b for b in buses if b.protocol == "CAN"), None)
        assert can is not None
        assert any("inject" in n.lower() for n in can.security_notes)

    def test_no_can_without_transceiver(self):
        r1 = _resistor("R1", "120", x=100, y=100)
        buses = infer_topology(_board(r1))
        assert all(b.protocol != "CAN" for b in buses)


# ---------------------------------------------------------------------------
# 1-Wire topology tests
# ---------------------------------------------------------------------------


class TestOneWireTopology:
    def test_ds18b20_detected(self):
        dev = _ic("U1", "DS18B20", x=100, y=100)
        buses = infer_topology(_board(dev))
        ow = next((b for b in buses if b.protocol == "1-Wire"), None)
        assert ow is not None

    def test_ds2401_detected(self):
        dev = _ic("U1", "DS2401", x=100, y=100)
        buses = infer_topology(_board(dev))
        assert any(b.protocol == "1-Wire" for b in buses)

    def test_4k7_pullup_associated(self):
        dev = _ic("U1", "DS18B20", x=100, y=100)
        r = _resistor("R1", "4.7k", x=130, y=100)

        buses = infer_topology(_board(dev, r))
        ow = next((b for b in buses if b.protocol == "1-Wire"), None)
        assert ow is not None
        assert ow.characteristics["pull_up_found"] is True
        assert "R1" in ow.nodes

    def test_security_notes_enumeration(self):
        dev = _ic("U1", "DS18B20", x=100, y=100)
        buses = infer_topology(_board(dev))
        ow = next((b for b in buses if b.protocol == "1-Wire"), None)
        assert any("enumerat" in n.lower() for n in ow.security_notes)

    def test_key_storage_note_for_ds2431(self):
        dev = _ic("U1", "DS2431", x=100, y=100)
        buses = infer_topology(_board(dev))
        ow = next((b for b in buses if b.protocol == "1-Wire"), None)
        assert ow is not None
        assert any("key" in n.lower() or "eeprom" in n.lower() for n in ow.security_notes)

    def test_no_1wire_without_known_device(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        buses = infer_topology(_board(mcu))
        assert all(b.protocol != "1-Wire" for b in buses)


# ---------------------------------------------------------------------------
# Empty / degenerate board tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_board_returns_empty_list(self):
        result = AnalysisResult(image_path="/fake/empty.jpg")
        buses = infer_topology(result)
        assert buses == []

    def test_board_with_only_passives(self):
        r1 = _resistor("R1", "10k", x=100, y=100)
        r2 = _resistor("R2", "100", x=200, y=200)
        buses = infer_topology(_board(r1, r2))
        assert buses == []

    def test_returns_list_of_bus_topology(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        buses = infer_topology(_board(mcu))
        assert isinstance(buses, list)
        for b in buses:
            assert isinstance(b, BusTopology)

    def test_sorted_by_confidence_descending(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        flash = _ic("U2", "W25Q128", x=160, y=100)
        bridge = _ic("U3", "CP2102", x=220, y=100)
        eeprom = _ic("U4", "AT24C256", x=280, y=100)
        r1 = _resistor("R1", "4.7k", x=240, y=80)

        buses = infer_topology(_board(mcu, flash, bridge, eeprom, r1))
        confidences = [b.confidence for b in buses]
        assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# Spatial proximity tests
# ---------------------------------------------------------------------------


class TestSpatialProximity:
    def test_far_resistor_not_associated_with_i2c(self):
        """Resistor 1000 px away from ICs must not trigger I2C detection."""
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        r_far = _resistor("R1", "4.7k", x=_far(100), y=_far(100))

        # Board is 800×600 so threshold ≈ 250 px; far resistor is 1000+ px away
        buses = infer_topology(_board(mcu, eeprom, r_far, w=800, h=600))
        i2c = next((b for b in buses if b.protocol == "I2C"), None)
        if i2c is not None:
            # If returned, pull-up must NOT be found (resistor was too far)
            assert i2c.characteristics["pull_ups_found"] is False

    def test_far_termination_not_associated_with_can(self):
        txcvr = _ic("U2", "MCP2551", x=100, y=100)
        r_far = _resistor("R1", "120", x=_far(100), y=_far(100))

        buses = infer_topology(_board(txcvr, r_far, w=800, h=600))
        can = next((b for b in buses if b.protocol == "CAN"), None)
        if can is not None:
            assert can.characteristics["termination_found"] is False

    def test_near_components_grouped(self):
        """Components within threshold must be grouped on the same bus."""
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        flash = _ic("U2", "W25Q128", x=140, y=100)  # 40 px away

        buses = infer_topology(_board(mcu, flash))
        spi = next((b for b in buses if b.protocol == "SPI"), None)
        assert spi is not None
        assert "U2" in spi.nodes


# ---------------------------------------------------------------------------
# Multi-bus board test
# ---------------------------------------------------------------------------


class TestMultipleBuses:
    def test_i2c_spi_uart_all_detected(self):
        """A realistic board with I2C + SPI + UART should detect all three."""
        mcu = _ic("U1", "STM32F103", x=150, y=150)
        eeprom = _ic("U2", "AT24C256", x=200, y=100)
        flash = _ic("U3", "W25Q64", x=200, y=200)
        bridge = _ic("U4", "CP2102", x=300, y=150)
        r_sda = _resistor("R1", "4.7k", x=175, y=80)
        r_scl = _resistor("R2", "4.7k", x=195, y=80)

        buses = infer_topology(_board(mcu, eeprom, flash, bridge, r_sda, r_scl))
        protocols = {b.protocol for b in buses}

        assert "I2C" in protocols
        assert "SPI" in protocols
        assert "UART" in protocols

    def test_can_and_spi_coexist(self):
        mcu = _ic("U1", "STM32F103", x=150, y=150)
        flash = _ic("U2", "W25Q128", x=200, y=150)
        txcvr = _ic("U3", "TJA1050", x=300, y=150)
        r_term = _resistor("R1", "120", x=330, y=150)

        buses = infer_topology(_board(mcu, flash, txcvr, r_term))
        protocols = {b.protocol for b in buses}

        assert "SPI" in protocols
        assert "CAN" in protocols

    def test_nodes_do_not_bleed_between_buses(self):
        """SPI flash nodes must not appear in CAN bus node list."""
        mcu = _ic("U1", "STM32F103", x=150, y=150)
        flash = _ic("U2", "W25Q128", x=200, y=150)
        txcvr = _ic("U3", "TJA1050", x=300, y=150)

        buses = infer_topology(_board(mcu, flash, txcvr))
        spi = next((b for b in buses if b.protocol == "SPI"), None)
        can = next((b for b in buses if b.protocol == "CAN"), None)

        if spi and can:
            spi_nodes = set(spi.nodes)
            can_nodes = set(can.nodes)
            # Flash chip ID must only appear in SPI
            assert "U2" not in can_nodes


# ---------------------------------------------------------------------------
# Confidence level tests
# ---------------------------------------------------------------------------


class TestConfidenceLevels:
    def test_more_evidence_raises_i2c_confidence(self):
        """Two pull-ups + peripheral → higher confidence than one pull-up alone."""
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        eeprom = _ic("U2", "AT24C256", x=160, y=100)
        sensor = _ic("U3", "BME280", x=200, y=100)
        r1 = _resistor("R1", "4.7k", x=130, y=80)
        r2 = _resistor("R2", "4.7k", x=150, y=80)

        buses_full = infer_topology(_board(mcu, eeprom, sensor, r1, r2))
        buses_minimal = infer_topology(_board(mcu, eeprom, r1))

        i2c_full = next((b for b in buses_full if b.protocol == "I2C"), None)
        i2c_min = next((b for b in buses_minimal if b.protocol == "I2C"), None)

        assert i2c_full is not None and i2c_min is not None
        assert i2c_full.confidence >= i2c_min.confidence

    def test_confidence_bounded_0_to_1(self):
        mcu = _ic("U1", "STM32F103", x=100, y=100)
        flash = _ic("U2", "W25Q128", x=120, y=100)
        bridge = _ic("U3", "CP2102", x=140, y=100)
        dev = _ic("U4", "DS18B20", x=160, y=100)
        r1 = _resistor("R1", "4.7k", x=110, y=80)

        buses = infer_topology(_board(mcu, flash, bridge, dev, r1))
        for b in buses:
            assert 0.0 <= b.confidence <= 1.0


# ---------------------------------------------------------------------------
# format_topology tests
# ---------------------------------------------------------------------------


class TestFormatTopology:
    def test_empty_returns_no_topology_message(self):
        text = format_topology([])
        assert "No protocol" in text

    def test_output_contains_protocol_name(self):
        bus = BusTopology(
            protocol="I2C",
            confidence=0.75,
            nodes=["U1", "U2"],
            characteristics={"pull_ups_found": True},
            security_notes=["No auth."],
        )
        text = format_topology([bus])
        assert "I2C" in text
        assert "75%" in text

    def test_security_notes_in_output(self):
        bus = BusTopology(
            protocol="CAN",
            confidence=0.8,
            nodes=["U3"],
            characteristics={},
            security_notes=["Injection possible."],
        )
        text = format_topology([bus])
        assert "Injection possible." in text

    def test_multiple_buses_all_shown(self):
        buses = [
            BusTopology("I2C", 0.8, ["U1"], {}, ["note"]),
            BusTopology("SPI", 0.7, ["U2"], {}, ["note"]),
        ]
        text = format_topology(buses)
        assert "I2C" in text
        assert "SPI" in text
