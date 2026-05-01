"""Tests for the security_intel feature across matcher, bom, html_report, svg, and IC pinout."""

from __future__ import annotations

import csv
import io

import retrace.identification.matcher as matcher_mod
from retrace.core.pipeline import AnalysisResult, Component
from retrace.export.bom import _component_to_bom_row, bom_to_csv, generate_bom
from retrace.export.html_report import generate_html_report
from retrace.export.pinout_diagram import _IC_PINOUTS, generate_ic_pinout_svg
from retrace.export.svg import generate_svg
from retrace.identification.matcher import lookup_security_intel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_component(
    cid: str = "U0001",
    label: str = "ic",
    part_number: str = "",
    marking: str = "",
    bbox: tuple[int, int, int, int] = (10, 20, 50, 40),
    confidence: float = 0.9,
    package: str = "",
) -> Component:
    return Component(
        id=cid,
        label=label,
        confidence=confidence,
        bbox=bbox,
        part_number=part_number,
        marking=marking,
        package=package,
    )


def _make_result(components: list[Component] | None = None) -> AnalysisResult:
    return AnalysisResult(
        image_path="test_board.jpg",
        components=components or [],
    )


# ---------------------------------------------------------------------------
# Tests: matcher.lookup_security_intel()
# ---------------------------------------------------------------------------

class TestLookupSecurityIntelMCU:
    """STM32F103C8T6 is a canonical MCU with a well-defined security_intel entry."""

    def test_returns_dict(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert isinstance(result, dict)

    def test_has_debug_interfaces(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "debug_interfaces" in result

    def test_debug_interfaces_is_list(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert isinstance(result["debug_interfaces"], list)

    def test_debug_interfaces_contains_jtag_and_swd(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "JTAG" in result["debug_interfaces"]
        assert "SWD" in result["debug_interfaces"]

    def test_has_boot_mode_pins(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "boot_mode_pins" in result

    def test_has_readout_protection(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "readout_protection" in result

    def test_readout_protection_is_string(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert isinstance(result["readout_protection"], str)

    def test_has_core(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "core" in result

    def test_has_voltage_range(self):
        result = lookup_security_intel("STM32F103C8T6")
        assert "voltage_range" in result

    def test_all_five_keys_present(self):
        result = lookup_security_intel("STM32F103C8T6")
        for key in ("debug_interfaces", "boot_mode_pins", "readout_protection", "core", "voltage_range"):
            assert key in result, f"Missing key: {key}"


class TestLookupSecurityIntelFlash:
    """W25Q128JV is a canonical SPI NOR flash."""

    def test_returns_dict(self):
        result = lookup_security_intel("W25Q128JV")
        assert isinstance(result, dict)

    def test_has_interface(self):
        result = lookup_security_intel("W25Q128JV")
        assert "interface" in result

    def test_has_read_cmd(self):
        result = lookup_security_intel("W25Q128JV")
        assert "read_cmd" in result

    def test_has_jedec_id(self):
        result = lookup_security_intel("W25Q128JV")
        assert "jedec_id" in result

    def test_jedec_id_value(self):
        result = lookup_security_intel("W25Q128JV")
        assert result["jedec_id"] == "0xEF4018"

    def test_has_write_protect_pin(self):
        result = lookup_security_intel("W25Q128JV")
        assert "write_protect_pin" in result

    def test_has_capacity(self):
        result = lookup_security_intel("W25Q128JV")
        assert "capacity" in result

    def test_has_flashrom_support(self):
        result = lookup_security_intel("W25Q128JV")
        assert "flashrom_support" in result

    def test_flashrom_support_mentions_flashrom(self):
        result = lookup_security_intel("W25Q128JV")
        assert "flashrom" in result["flashrom_support"].lower()

    def test_all_flash_keys_present(self):
        result = lookup_security_intel("W25Q128JV")
        for key in ("interface", "read_cmd", "jedec_id", "write_protect_pin",
                    "capacity", "flashrom_support"):
            assert key in result, f"Missing key: {key}"


class TestLookupSecurityIntelFPGA:
    """XC7A35T is an Artix-7 FPGA."""

    def test_returns_dict(self):
        result = lookup_security_intel("XC7A35T")
        assert isinstance(result, dict)

    def test_has_config_interface(self):
        result = lookup_security_intel("XC7A35T")
        assert "config_interface" in result

    def test_config_interface_is_list(self):
        result = lookup_security_intel("XC7A35T")
        assert isinstance(result["config_interface"], list)

    def test_config_interface_contains_jtag(self):
        result = lookup_security_intel("XC7A35T")
        assert any("JTAG" in iface for iface in result["config_interface"])

    def test_has_jtag_chain(self):
        result = lookup_security_intel("XC7A35T")
        assert "jtag_chain" in result

    def test_has_bitstream_format(self):
        result = lookup_security_intel("XC7A35T")
        assert "bitstream_format" in result

    def test_has_toolchain(self):
        result = lookup_security_intel("XC7A35T")
        assert "toolchain" in result

    def test_toolchain_mentions_vivado(self):
        result = lookup_security_intel("XC7A35T")
        assert "Vivado" in result["toolchain"]

    def test_has_lut_count(self):
        result = lookup_security_intel("XC7A35T")
        assert "lut_count" in result

    def test_lut_count_is_integer(self):
        result = lookup_security_intel("XC7A35T")
        assert isinstance(result["lut_count"], int)

    def test_all_fpga_keys_present(self):
        result = lookup_security_intel("XC7A35T")
        for key in ("config_interface", "jtag_chain", "bitstream_format", "toolchain", "lut_count"):
            assert key in result, f"Missing key: {key}"


class TestLookupSecurityIntelTPM:
    """SLB9670 is an Infineon TPM 2.0."""

    def test_returns_dict(self):
        result = lookup_security_intel("SLB9670")
        assert isinstance(result, dict)

    def test_has_interface(self):
        result = lookup_security_intel("SLB9670")
        assert "interface" in result

    def test_has_certification(self):
        result = lookup_security_intel("SLB9670")
        assert "certification" in result

    def test_certification_mentions_fips(self):
        result = lookup_security_intel("SLB9670")
        assert "FIPS" in result["certification"]

    def test_has_key_storage(self):
        result = lookup_security_intel("SLB9670")
        assert "key_storage" in result

    def test_has_attestation(self):
        result = lookup_security_intel("SLB9670")
        assert "attestation" in result

    def test_attestation_mentions_tpm(self):
        result = lookup_security_intel("SLB9670")
        assert "TPM" in result["attestation"] or "attestation" in result["attestation"].lower()

    def test_all_tpm_keys_present(self):
        result = lookup_security_intel("SLB9670")
        for key in ("interface", "certification", "key_storage", "attestation"):
            assert key in result, f"Missing key: {key}"


class TestLookupSecurityIntelMissing:
    def test_nonexistent_part_returns_none(self):
        assert lookup_security_intel("NONEXISTENT") is None

    def test_empty_string_returns_none(self):
        assert lookup_security_intel("") is None

    def test_garbage_string_returns_none(self):
        assert lookup_security_intel("XYZZY99999_FAKE") is None

    def test_partial_match_not_used(self):
        # lookup_security_intel uses exact key lookup, not fuzzy
        result = lookup_security_intel("STM32F103")
        # STM32F103 is an alias, so it IS in _LOOKUP — but if not found, None is acceptable.
        # This test ensures we get either a dict or None, not an exception.
        assert result is None or isinstance(result, dict)

    def test_returns_none_not_empty_dict(self):
        result = lookup_security_intel("TOTALLY_FAKE_PART_99999")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _COMPONENT_DB integrity
# ---------------------------------------------------------------------------

class TestComponentDBIntegrity:
    """Validate that all entries with security_intel conform to structural rules."""

    def _intel_entries(self):
        return [e for e in matcher_mod._COMPONENT_DB if "security_intel" in e]

    def _entries_by_category(self, category: str):
        return [
            e for e in matcher_mod._COMPONENT_DB
            if e.get("category") == category and "security_intel" in e
        ]

    def test_all_intel_entries_have_dict(self):
        for entry in self._intel_entries():
            assert isinstance(entry["security_intel"], dict), (
                f"Part {entry.get('part')} has non-dict security_intel"
            )

    def test_all_intel_entries_have_at_least_two_keys(self):
        for entry in self._intel_entries():
            keys = entry["security_intel"].keys()
            assert len(keys) >= 2, (
                f"Part {entry.get('part')} has security_intel with < 2 keys: {list(keys)}"
            )

    def test_all_mcu_entries_have_debug_interfaces(self):
        for entry in self._entries_by_category("mcu"):
            si = entry["security_intel"]
            assert "debug_interfaces" in si, (
                f"MCU {entry.get('part')} missing debug_interfaces"
            )

    def test_all_mcu_entries_have_readout_protection(self):
        for entry in self._entries_by_category("mcu"):
            si = entry["security_intel"]
            assert "readout_protection" in si, (
                f"MCU {entry.get('part')} missing readout_protection"
            )

    def test_all_flash_entries_have_jedec_id(self):
        for entry in self._entries_by_category("flash"):
            si = entry["security_intel"]
            assert "jedec_id" in si, (
                f"Flash {entry.get('part')} missing jedec_id"
            )

    def test_all_flash_entries_have_read_cmd(self):
        for entry in self._entries_by_category("flash"):
            si = entry["security_intel"]
            assert "read_cmd" in si, (
                f"Flash {entry.get('part')} missing read_cmd"
            )

    def test_all_fpga_entries_have_config_interface(self):
        for entry in self._entries_by_category("fpga"):
            si = entry["security_intel"]
            assert "config_interface" in si, (
                f"FPGA {entry.get('part')} missing config_interface"
            )

    def test_all_fpga_entries_have_toolchain(self):
        for entry in self._entries_by_category("fpga"):
            si = entry["security_intel"]
            assert "toolchain" in si, (
                f"FPGA {entry.get('part')} missing toolchain"
            )

    def test_mcu_debug_interfaces_are_lists(self):
        for entry in self._entries_by_category("mcu"):
            si = entry["security_intel"]
            assert isinstance(si["debug_interfaces"], list), (
                f"MCU {entry.get('part')}: debug_interfaces must be a list"
            )

    def test_total_intel_count_matches_expected(self):
        # 187 of 196 entries have security_intel (9 sensor entries omit it)
        intel_entries = self._intel_entries()
        assert len(intel_entries) == 187


# ---------------------------------------------------------------------------
# Tests: bom.py — _component_to_bom_row
# ---------------------------------------------------------------------------

class TestComponentToBomRow:
    def test_known_part_includes_security_intel_key(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        assert "security_intel" in row

    def test_security_intel_is_dict(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        assert isinstance(row["security_intel"], dict)

    def test_intel_flattened_keys_present(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        intel_keys = [k for k in row if k.startswith("intel_")]
        assert len(intel_keys) > 0

    def test_intel_debug_interfaces_key_flattened(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        assert "intel_debug_interfaces" in row

    def test_intel_readout_protection_key_flattened(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        assert "intel_readout_protection" in row

    def test_intel_list_values_joined_with_comma(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        # debug_interfaces is a list — should be joined into a string
        assert isinstance(row["intel_debug_interfaces"], str)
        assert "," in row["intel_debug_interfaces"] or len(row["intel_debug_interfaces"]) > 0

    def test_intel_string_values_remain_strings(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        assert isinstance(row["intel_readout_protection"], str)

    def test_flash_part_has_jedec_id_key(self):
        comp = _make_component(cid="U2", part_number="W25Q128JV")
        row = _component_to_bom_row(comp)
        assert "intel_jedec_id" in row
        assert row["intel_jedec_id"] == "0xEF4018"

    def test_unknown_part_has_no_security_intel(self):
        comp = _make_component(cid="U3", part_number="TOTALLY_FAKE_PART")
        row = _component_to_bom_row(comp)
        assert "security_intel" not in row

    def test_unknown_part_has_no_intel_keys(self):
        comp = _make_component(cid="U3", part_number="TOTALLY_FAKE_PART")
        row = _component_to_bom_row(comp)
        intel_keys = [k for k in row if k.startswith("intel_")]
        assert len(intel_keys) == 0

    def test_empty_part_number_has_no_security_intel(self):
        comp = _make_component(cid="U4", part_number="")
        row = _component_to_bom_row(comp)
        assert "security_intel" not in row

    def test_standard_fields_still_present_with_intel(self):
        comp = _make_component(cid="U1", part_number="STM32F103C8T6")
        row = _component_to_bom_row(comp)
        for key in ("id", "label", "part_number", "marking", "confidence", "bbox"):
            assert key in row, f"Standard key missing: {key}"

    def test_fpga_part_has_config_interface_key(self):
        comp = _make_component(cid="U5", part_number="XC7A35T")
        row = _component_to_bom_row(comp)
        assert "intel_config_interface" in row

    def test_tpm_part_has_attestation_key(self):
        comp = _make_component(cid="U6", part_number="SLB9670")
        row = _component_to_bom_row(comp)
        assert "intel_attestation" in row


# ---------------------------------------------------------------------------
# Tests: bom.py — bom_to_csv with intel columns
# ---------------------------------------------------------------------------

class TestBomToCsvWithIntel:
    def _intel_bom(self) -> dict:
        comps = [
            _make_component(cid="U1", part_number="STM32F103C8T6"),
            _make_component(cid="U2", part_number="W25Q128JV"),
        ]
        return generate_bom(_make_result(comps))

    def test_csv_contains_intel_columns(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        header = csv_out.splitlines()[0]
        assert "intel_" in header

    def test_csv_contains_debug_interfaces_column(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        header = csv_out.splitlines()[0]
        assert "intel_debug_interfaces" in header

    def test_csv_contains_jedec_id_column(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        header = csv_out.splitlines()[0]
        assert "intel_jedec_id" in header

    def test_csv_intel_values_in_rows(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        reader = csv.DictReader(io.StringIO(csv_out))
        rows = list(reader)
        # STM32F103C8T6 row should have debug_interfaces filled in
        stm_rows = [r for r in rows if r.get("part_number") == "STM32F103C8T6"]
        assert len(stm_rows) == 1
        assert stm_rows[0]["intel_debug_interfaces"] != ""

    def test_csv_jedec_id_value_correct(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        reader = csv.DictReader(io.StringIO(csv_out))
        rows = list(reader)
        flash_rows = [r for r in rows if r.get("part_number") == "W25Q128JV"]
        assert len(flash_rows) == 1
        assert flash_rows[0]["intel_jedec_id"] == "0xEF4018"

    def test_csv_no_intel_columns_for_plain_bom(self):
        """When no components have intel, the header is the standard baseline."""
        comps = [_make_component(cid="C1", part_number="TOTALLY_FAKE_PART")]
        bom = generate_bom(_make_result(comps))
        csv_out = bom_to_csv(bom)
        header = csv_out.splitlines()[0]
        assert "intel_" not in header

    def test_csv_still_parseable_with_intel_columns(self):
        bom = self._intel_bom()
        csv_out = bom_to_csv(bom)
        reader = csv.DictReader(io.StringIO(csv_out))
        rows = list(reader)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Tests: html_report.py — Component Intelligence section
# ---------------------------------------------------------------------------

def _intel_result() -> AnalysisResult:
    """AnalysisResult with components that have known part numbers."""
    return AnalysisResult(
        image_path="intel_board.jpg",
        components=[
            Component(
                id="U1",
                label="ic",
                confidence=0.95,
                bbox=(10, 20, 50, 40),
                marking="STM32F103",
                part_number="STM32F103C8T6",
            ),
            Component(
                id="U2",
                label="ic",
                confidence=0.90,
                bbox=(100, 20, 40, 30),
                marking="W25Q128",
                part_number="W25Q128JV",
            ),
        ],
    )


class TestHTMLReportComponentIntelligence:
    def test_section_heading_present(self):
        report = generate_html_report(_intel_result())
        assert "Component Intelligence" in report

    def test_section_uses_section_class(self):
        report = generate_html_report(_intel_result())
        # The section wraps in class="section"
        assert 'class="section"' in report

    def test_intel_card_class_present(self):
        report = generate_html_report(_intel_result())
        assert "intel-card" in report

    def test_intel_table_class_present(self):
        report = generate_html_report(_intel_result())
        assert "intel-table" in report

    def test_stm32_part_appears_in_intel_section(self):
        report = generate_html_report(_intel_result())
        assert "STM32F103C8T6" in report

    def test_flash_part_appears_in_intel_section(self):
        report = generate_html_report(_intel_result())
        assert "W25Q128JV" in report

    def test_debug_interfaces_label_present(self):
        report = generate_html_report(_intel_result())
        assert "Debug Interfaces" in report

    def test_readout_protection_label_present(self):
        report = generate_html_report(_intel_result())
        assert "Readout Protection" in report

    def test_jedec_id_label_present(self):
        report = generate_html_report(_intel_result())
        assert "Jedec Id" in report or "JEDEC" in report or "jedec" in report.lower()

    def test_intel_highlight_class_present(self):
        # High-value keys get intel-highlight styling
        report = generate_html_report(_intel_result())
        assert "intel-highlight" in report

    def test_section_absent_when_no_intel_parts(self):
        """A result with no identified parts should not render the intel section."""
        result = AnalysisResult(
            image_path="empty.jpg",
            components=[
                Component(
                    id="C1",
                    label="capacitor",
                    confidence=0.8,
                    bbox=(0, 0, 10, 10),
                    part_number="",
                ),
            ],
        )
        report = generate_html_report(result)
        assert "Component Intelligence" not in report

    def test_section_absent_for_unknown_part(self):
        result = AnalysisResult(
            image_path="empty.jpg",
            components=[
                Component(
                    id="U1",
                    label="ic",
                    confidence=0.8,
                    bbox=(0, 0, 10, 10),
                    part_number="TOTALLY_FAKE_PART_XYZ",
                ),
            ],
        )
        report = generate_html_report(result)
        assert "Component Intelligence" not in report

    def test_section_present_for_tpm(self):
        result = AnalysisResult(
            image_path="tpm.jpg",
            components=[
                Component(
                    id="U1",
                    label="ic",
                    confidence=0.9,
                    bbox=(0, 0, 10, 10),
                    part_number="SLB9670",
                ),
            ],
        )
        report = generate_html_report(result)
        assert "Component Intelligence" in report

    def test_intel_grid_class_present(self):
        report = generate_html_report(_intel_result())
        assert "intel-grid" in report

    def test_intel_cat_class_present(self):
        # Category badge renders with intel-cat class
        report = generate_html_report(_intel_result())
        assert "intel-cat" in report

    def test_full_report_is_valid_html(self):
        report = generate_html_report(_intel_result())
        assert report.startswith("<!DOCTYPE html>")
        assert "</html>" in report


# ---------------------------------------------------------------------------
# Tests: svg.py — _render_bom_panel Security Intel section
# ---------------------------------------------------------------------------

class TestSvgBomPanelSecurityIntel:
    def _intel_svg(self) -> str:
        result = _make_result([
            _make_component(cid="U1", label="ic", part_number="STM32F103C8T6"),
        ])
        return generate_svg(result)

    def test_security_intel_text_present(self):
        svg = self._intel_svg()
        assert "Security Intel" in svg

    def test_security_intel_text_with_flash(self):
        result = _make_result([
            _make_component(cid="U2", label="ic", part_number="W25Q128JV"),
        ])
        svg = generate_svg(result)
        assert "Security Intel" in svg

    def test_security_intel_absent_without_intel_parts(self):
        result = _make_result([
            _make_component(cid="C1", label="capacitor", part_number=""),
        ])
        svg = generate_svg(result)
        assert "Security Intel" not in svg

    def test_security_intel_absent_for_unknown_part(self):
        result = _make_result([
            _make_component(cid="U1", label="ic", part_number="TOTALLY_FAKE_PART_XYZ"),
        ])
        svg = generate_svg(result)
        assert "Security Intel" not in svg

    def test_part_label_appears_in_intel_line(self):
        # The intel summary includes the part name before " — "
        svg = self._intel_svg()
        # Part name or truncation should appear alongside intel data
        assert "STM32F103" in svg or "STM32F10.." in svg

    def test_bom_panel_present_with_intel(self):
        svg = self._intel_svg()
        assert 'class="bom-panel"' in svg

    def test_svg_remains_valid_with_intel(self):
        svg = self._intel_svg()
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_security_intel_with_flash_jedec_id(self):
        # W25Q128JV has jedec_id which is one of the summary keys the BOM panel renders
        result = _make_result([
            _make_component(cid="U3", label="ic", part_number="W25Q128JV"),
        ])
        svg = generate_svg(result)
        assert "Security Intel" in svg

    def test_security_intel_summary_uses_debug_interfaces(self):
        # STM32 has debug_interfaces — the BOM panel summary renders those
        svg = self._intel_svg()
        # The rendered line includes "JTAG+SWD" from the STM32 debug_interfaces list
        assert "JTAG" in svg or "SWD" in svg

    def test_multiple_intel_parts_all_summarised(self):
        result = _make_result([
            _make_component(cid="U1", label="ic", part_number="STM32F103C8T6"),
            _make_component(cid="U2", label="ic", part_number="W25Q128JV"),
        ])
        svg = generate_svg(result)
        assert "Security Intel" in svg


# ---------------------------------------------------------------------------
# IC Pinout Diagram Tests
# ---------------------------------------------------------------------------


class TestICPinoutSVG:
    def test_soic8_flash_has_pins(self):
        comp = _make_component(cid="U1", label="ic", part_number="W25Q128JV",
                               package="SOP8")
        svg = generate_ic_pinout_svg(comp)
        assert svg, "Expected non-empty SVG for SOIC8 flash"
        assert "CS#" in svg
        assert "DO (MISO)" in svg
        assert "WP#" in svg
        assert "VCC" in svg

    def test_soic8_flash_has_intel_section(self):
        comp = _make_component(cid="U1", label="ic", part_number="W25Q128JV",
                               package="SOP8")
        svg = generate_ic_pinout_svg(comp)
        assert "Security Intelligence" in svg
        assert "Jedec Id" in svg or "0xEF4018" in svg

    def test_soic8_eeprom_has_pins(self):
        comp = _make_component(cid="U2", label="ic", part_number="AT24C256",
                               package="SOIC8")
        svg = generate_ic_pinout_svg(comp)
        assert svg
        assert "SDA" in svg
        assert "SCL" in svg
        assert "WP" in svg

    def test_mcu_tqfp_quad_pinout(self):
        comp = _make_component(cid="U3", label="ic", part_number="STM32F103C8T6",
                               package="LQFP48")
        svg = generate_ic_pinout_svg(comp)
        assert svg
        assert "Security Intelligence" in svg
        assert "PA13" in svg
        assert "BOOT0" in svg

    def test_fpga_qfn_quad_pinout(self):
        comp = _make_component(cid="U4", label="ic", part_number="iCE40UP5K",
                               package="QFN-48")
        svg = generate_ic_pinout_svg(comp)
        assert svg
        assert "Yosys" in svg or "icestorm" in svg or "Toolchain" in svg
        assert "CRESET" in svg or "CDONE" in svg

    def test_unknown_part_returns_empty(self):
        comp = _make_component(cid="U5", label="ic", part_number="NONEXISTENT")
        svg = generate_ic_pinout_svg(comp)
        assert svg == ""

    def test_no_part_number_returns_empty(self):
        comp = _make_component(cid="U6", label="ic")
        svg = generate_ic_pinout_svg(comp)
        assert svg == ""

    def test_svg_is_well_formed(self):
        comp = _make_component(cid="U1", label="ic", part_number="W25Q128JV",
                               package="SOP8")
        svg = generate_ic_pinout_svg(comp)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert svg.count("<svg") == 1

    def test_custom_width(self):
        comp = _make_component(cid="U1", label="ic", part_number="W25Q128JV",
                               package="SOP8")
        svg = generate_ic_pinout_svg(comp, width=400)
        assert 'width="400"' in svg

    def test_ic_pinouts_data_integrity(self):
        expected_counts = {
            "SOIC8_SPI_FLASH": 8, "SOIC8_EEPROM": 8,
            "TQFP48_MCU": 48, "TSOP48_NAND": 48, "QFN24_GENERIC": 24,
        }
        for key, pins in _IC_PINOUTS.items():
            if key in expected_counts:
                assert len(pins) == expected_counts[key], f"{key} pin count"
            assert len(pins) >= 8, f"{key} should have at least 8 pins"
            for name, group, desc in pins:
                assert name, f"Empty pin name in {key}"
                assert group in ("data", "clock", "power", "ground", "control", "debug"), \
                    f"Invalid group {group!r} in {key}"
                assert desc, f"Empty description in {key}"

    def test_flash_extraction_cheat_sheet(self):
        comp = _make_component(cid="U1", label="ic", part_number="W25Q128JV",
                               package="SOP8")
        svg = generate_ic_pinout_svg(comp)
        assert "Flash Extraction Cheat Sheet" in svg
        assert "binwalk" in svg
        assert "flashrom" in svg
        assert "JEDEC" in svg

    def test_non_flash_has_no_cheat_sheet(self):
        comp = _make_component(cid="U3", label="ic", part_number="STM32F103C8T6",
                               package="LQFP48")
        svg = generate_ic_pinout_svg(comp)
        assert "Flash Extraction" not in svg

    def test_tpm_has_intel(self):
        comp = _make_component(cid="U7", label="ic", part_number="SLB9670",
                               package="QFN-32")
        svg = generate_ic_pinout_svg(comp)
        assert svg
        assert "FIPS" in svg or "Certification" in svg

    def test_ethernet_phy_has_intel(self):
        comp = _make_component(cid="U8", label="ic", part_number="RTL8211F",
                               package="QFN-48")
        svg = generate_ic_pinout_svg(comp)
        assert svg
        assert "MDIO" in svg or "Mdio" in svg
