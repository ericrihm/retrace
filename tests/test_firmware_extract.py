"""Tests for firmware extraction cheat sheet generator."""

from __future__ import annotations

from retrace.core.pipeline import AnalysisResult, Component
from retrace.export.firmware_extract import (
    generate_extraction_guide,
    format_extraction_guide,
    _classify_storage,
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
# Classification tests
# ---------------------------------------------------------------------------

class TestClassifyStorage:
    def test_w25q_is_flash(self):
        assert _classify_storage(_comp("U1", marking="W25Q128JV")) == "spi_flash"

    def test_mx25_is_flash(self):
        assert _classify_storage(_comp("U1", marking="MX25L25645G")) == "spi_flash"

    def test_at25_is_flash(self):
        assert _classify_storage(_comp("U1", marking="AT25SF128A")) == "spi_flash"

    def test_is25_is_flash(self):
        assert _classify_storage(_comp("U1", marking="IS25LP128")) == "spi_flash"

    def test_flash_keyword(self):
        assert _classify_storage(_comp("U1", marking="Flash Memory")) == "spi_flash"

    def test_emmc(self):
        assert _classify_storage(_comp("U1", marking="MTFC4GACAJCN")) == "emmc"

    def test_eeprom_at24(self):
        assert _classify_storage(_comp("U1", marking="AT24C256")) == "eeprom"

    def test_eeprom_keyword(self):
        assert _classify_storage(_comp("U1", marking="EEPROM 128K")) == "eeprom"

    def test_mcu_not_storage(self):
        assert _classify_storage(_comp("U1", marking="STM32F103")) is None

    def test_resistor_not_storage(self):
        assert _classify_storage(_comp("R1", label="resistor", marking="10K")) is None


# ---------------------------------------------------------------------------
# Guide generation — SPI flash
# ---------------------------------------------------------------------------

class TestSPIFlashGuide:
    def test_basic_flash_guide(self):
        flash = _comp("U1", marking="W25Q128JV", part_number="W25Q128JVSIQ")
        guides = generate_extraction_guide(_board(flash))
        assert len(guides) == 1
        assert guides[0]["storage_type"] == "spi_flash"
        assert guides[0]["marking"] == "W25Q128JV"

    def test_flash_has_flashrom_command(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        cmds = guides[0]["commands"]
        flashrom_cmds = [c for c in cmds if c["tool"] == "flashrom"]
        assert len(flashrom_cmds) >= 1
        assert "flashrom" in flashrom_cmds[0]["command"]

    def test_flash_has_verify_command(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        cmds = guides[0]["commands"]
        verify_cmds = [c for c in cmds if "verify" in c["description"].lower()]
        assert len(verify_cmds) == 1

    def test_flash_has_wiring_diagram(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        wiring = guides[0].get("wiring", {})
        assert "VCC" in wiring
        assert "GND" in wiring
        assert "CLK" in wiring
        assert "CS#" in wiring

    def test_flash_with_security_intel(self):
        flash = _comp("U1", marking="W25Q128JV")
        flash._security_intel = {
            "jedec_id": "0xEF4018",
            "flashrom_support": "flashrom -p ch341a_spi -c W25Q128.V -r fw.bin",
            "capacity": "128Mbit (16MB)",
        }
        guides = generate_extraction_guide(_board(flash))
        assert guides[0]["jedec_id"] == "0xEF4018"
        assert guides[0]["capacity"] == "128Mbit (16MB)"
        flashrom_cmds = [c for c in guides[0]["commands"] if c["tool"] == "flashrom"]
        assert "W25Q128.V" in flashrom_cmds[0]["command"]

    def test_flash_jedec_probe_command(self):
        flash = _comp("U1", marking="W25Q128JV")
        flash._security_intel = {"jedec_id": "0xEF4018"}
        guides = generate_extraction_guide(_board(flash))
        spi_cmds = [c for c in guides[0]["commands"] if c["tool"] == "spi_manual"]
        assert any("0x9F" in c["command"] for c in spi_cmds)

    def test_flash_with_read_cmd_adds_spi_manual_command(self):
        """Line 105 — read_cmd in security intel adds a manual SPI read command."""
        flash = _comp("U1", marking="W25Q128JV")
        flash._security_intel = {"read_cmd": "0x03 <addr24> <data>"}
        guides = generate_extraction_guide(_board(flash))
        spi_cmds = [c for c in guides[0]["commands"] if c["tool"] == "spi_manual"]
        assert any("Manual read command" in c["description"] for c in spi_cmds)


# ---------------------------------------------------------------------------
# Guide generation — eMMC
# ---------------------------------------------------------------------------

class TestEMMCGuide:
    def test_basic_emmc_guide(self):
        emmc = _comp("U1", marking="MTFC4GACAJCN")
        guides = generate_extraction_guide(_board(emmc))
        assert len(guides) == 1
        assert guides[0]["storage_type"] == "emmc"

    def test_emmc_has_dd_command(self):
        emmc = _comp("U1", marking="MTFC4GACAJCN")
        guides = generate_extraction_guide(_board(emmc))
        dd_cmds = [c for c in guides[0]["commands"] if c["tool"] == "dd"]
        assert len(dd_cmds) == 1
        assert "dd if=" in dd_cmds[0]["command"]


# ---------------------------------------------------------------------------
# Guide generation — EEPROM
# ---------------------------------------------------------------------------

class TestEEPROMGuide:
    def test_basic_eeprom_guide(self):
        eeprom = _comp("U1", marking="AT24C256")
        guides = generate_extraction_guide(_board(eeprom))
        assert len(guides) == 1
        assert guides[0]["storage_type"] == "eeprom"

    def test_eeprom_has_i2c_info(self):
        eeprom = _comp("U1", marking="AT24C256")
        guides = generate_extraction_guide(_board(eeprom))
        i2c_cmds = [c for c in guides[0]["commands"] if c["tool"] == "i2c"]
        assert len(i2c_cmds) == 1
        assert "0x50" in i2c_cmds[0]["command"]


# ---------------------------------------------------------------------------
# Multiple chips
# ---------------------------------------------------------------------------

class TestMultipleChips:
    def test_multiple_flash_chips(self):
        f1 = _comp("U1", marking="W25Q128JV")
        f2 = _comp("U2", marking="MX25L25645G")
        guides = generate_extraction_guide(_board(f1, f2))
        assert len(guides) == 2

    def test_mixed_storage_types(self):
        flash = _comp("U1", marking="W25Q128JV")
        emmc = _comp("U2", marking="MTFC4GACAJCN")
        eeprom = _comp("U3", marking="AT24C256")
        guides = generate_extraction_guide(_board(flash, emmc, eeprom))
        types = {g["storage_type"] for g in guides}
        assert types == {"spi_flash", "emmc", "eeprom"}


# ---------------------------------------------------------------------------
# Empty / no storage
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_board(self):
        assert generate_extraction_guide(_board()) == []

    def test_no_storage_chips(self):
        mcu = _comp("U1", marking="STM32F103")
        r = _comp("R1", label="resistor", marking="10K")
        assert generate_extraction_guide(_board(mcu, r)) == []

    def test_component_without_marking(self):
        flash = _comp("U1", marking="", part_number="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        assert len(guides) == 1


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

class TestFormatExtractionGuide:
    def test_empty_gives_no_chips_message(self):
        text = format_extraction_guide([])
        assert "No extractable" in text

    def test_format_contains_chip_name(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "W25Q128JV" in text

    def test_format_contains_flashrom(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "flashrom" in text

    def test_format_contains_wiring(self):
        flash = _comp("U1", marking="W25Q128JV")
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "Wiring" in text
        assert "VCC" in text

    def test_format_with_capacity(self):
        flash = _comp("U1", marking="W25Q128JV")
        flash._security_intel = {"capacity": "128Mbit (16MB)"}
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "128Mbit" in text

    def test_format_shows_part_number(self):
        """Line 162 — part_number in guide dict appears in formatted output."""
        flash = _comp("U1", marking="W25Q128JV", part_number="W25Q128JVSIQ")
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "Part:" in text
        assert "W25Q128JVSIQ" in text

    def test_format_shows_jedec_id(self):
        """Line 167 — JEDEC ID in guide dict appears in formatted output."""
        flash = _comp("U1", marking="W25Q128JV")
        flash._security_intel = {"jedec_id": "0xEF4018"}
        guides = generate_extraction_guide(_board(flash))
        text = format_extraction_guide(guides)
        assert "JEDEC ID:" in text
        assert "0xEF4018" in text
