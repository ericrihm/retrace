"""Tests for Sigrok session export."""

from __future__ import annotations

import zipfile
import io

from retrace.export.sigrok import (
    generate_sigrok_metadata,
    generate_sigrok_session,
    get_decoder_config,
    format_sigrok_summary,
)


def _uart_finding():
    return {"interface": "UART", "component_id": "J1", "severity": "medium"}


def _spi_finding():
    return {"interface": "SPI", "component_id": "J2", "severity": "medium"}


def _i2c_finding():
    return {"interface": "I2C", "component_id": "J3", "severity": "low"}


def _jtag_finding():
    return {"interface": "JTAG", "component_id": "J4", "severity": "high"}


def _swd_finding():
    return {"interface": "SWD", "component_id": "J5", "severity": "high"}


# ---------------------------------------------------------------------------
# Metadata generation
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_empty_interfaces(self):
        meta = generate_sigrok_metadata([])
        assert "total probes" in meta
        assert "0" in meta

    def test_uart_channels(self):
        meta = generate_sigrok_metadata([_uart_finding()])
        assert "UART_RX" in meta
        assert "UART_TX" in meta
        assert "total probes = 2" in meta

    def test_spi_channels(self):
        meta = generate_sigrok_metadata([_spi_finding()])
        assert "SPI_CLK" in meta
        assert "SPI_MOSI" in meta
        assert "SPI_MISO" in meta
        assert "SPI_CS#" in meta
        assert "total probes = 4" in meta

    def test_i2c_channels(self):
        meta = generate_sigrok_metadata([_i2c_finding()])
        assert "I2C_SCL" in meta
        assert "I2C_SDA" in meta

    def test_jtag_channels(self):
        meta = generate_sigrok_metadata([_jtag_finding()])
        assert "JTAG_TDI" in meta
        assert "JTAG_TDO" in meta
        assert "JTAG_TCK" in meta
        assert "JTAG_TMS" in meta

    def test_swd_channels(self):
        meta = generate_sigrok_metadata([_swd_finding()])
        assert "SWD_SWDIO" in meta
        assert "SWD_SWCLK" in meta

    def test_multiple_interfaces(self):
        meta = generate_sigrok_metadata([_uart_finding(), _spi_finding()])
        assert "total probes = 6" in meta

    def test_sample_rate(self):
        meta = generate_sigrok_metadata([_uart_finding()], sample_rate=4_000_000)
        assert "4000000" in meta

    def test_board_name(self):
        meta = generate_sigrok_metadata([_uart_finding()], board_name="MyBoard")
        assert "MyBoard" in meta

    def test_unknown_interface_skipped(self):
        meta = generate_sigrok_metadata([{"interface": "UNKNOWN", "component_id": "X"}])
        assert "total probes = 0" in meta

    def test_retrace_version_in_metadata(self):
        meta = generate_sigrok_metadata([])
        assert "retrace version" in meta


# ---------------------------------------------------------------------------
# Session ZIP generation
# ---------------------------------------------------------------------------

class TestSession:
    def test_returns_valid_zip(self):
        data = generate_sigrok_session([_uart_finding()])
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert "version" in zf.namelist()
        assert "metadata" in zf.namelist()

    def test_version_is_2(self):
        data = generate_sigrok_session([_uart_finding()])
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert zf.read("version").decode() == "2"

    def test_metadata_contains_channels(self):
        data = generate_sigrok_session([_spi_finding()])
        zf = zipfile.ZipFile(io.BytesIO(data))
        meta = zf.read("metadata").decode()
        assert "SPI_CLK" in meta

    def test_empty_session(self):
        data = generate_sigrok_session([])
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert "metadata" in zf.namelist()


# ---------------------------------------------------------------------------
# Decoder config lookup
# ---------------------------------------------------------------------------

class TestDecoderConfig:
    def test_uart_decoder(self):
        cfg = get_decoder_config("UART")
        assert cfg["decoder"] == "uart"
        assert cfg["options"]["baudrate"] == 115200

    def test_spi_decoder(self):
        cfg = get_decoder_config("SPI")
        assert cfg["decoder"] == "spi"

    def test_unknown_returns_none(self):
        assert get_decoder_config("UNKNOWN") is None


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def test_empty_returns_message(self):
        text = format_sigrok_summary([])
        assert "No interfaces" in text

    def test_uart_summary(self):
        text = format_sigrok_summary([_uart_finding()])
        assert "UART" in text
        assert "CH0" in text
        assert "baudrate" in text

    def test_multiple_interfaces_summary(self):
        text = format_sigrok_summary([_uart_finding(), _jtag_finding()])
        assert "Total channels: 6" in text

    def test_import_instructions(self):
        text = format_sigrok_summary([_uart_finding()])
        assert "PulseView" in text

    def test_unknown_interface_skipped_in_summary(self):
        """Line 140 — interface not in _PROTOCOL_DECODERS is silently skipped."""
        unknown = {"interface": "CAN", "component_id": "J5", "severity": "low"}
        text = format_sigrok_summary([unknown])
        # No CAN entry in summary (unknown interface skipped)
        assert "CAN" not in text or "No interfaces" in text

    def test_mixed_known_and_unknown_interface(self):
        """Line 140 — unknown interface skipped, known interface still rendered."""
        unknown = {"interface": "CAN", "component_id": "J5", "severity": "low"}
        text = format_sigrok_summary([unknown, _uart_finding()])
        assert "UART" in text
