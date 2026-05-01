"""Tests for the component identification matcher."""

from __future__ import annotations

import json

import retrace.identification.matcher as matcher_mod
from retrace.core.pipeline import Component
from retrace.identification.matcher import identify_components, lookup_part

# ---------------------------------------------------------------------------
# Tests: lookup_part()
# ---------------------------------------------------------------------------

def test_exact_match_stm32():
    result = lookup_part("STM32F103")
    assert result is not None
    assert "STM32" in result["part"]


def test_exact_match_esp32():
    result = lookup_part("ESP32")
    assert result is not None
    assert result["part"] == "ESP32-WROOM-32"


def test_exact_match_ams1117():
    result = lookup_part("AMS1117")
    assert result is not None
    assert "AMS1117" in result["part"]


def test_fuzzy_match_partial_marking():
    """'ATmega328' should fuzzily match ATmega328P."""
    result = lookup_part("ATmega328")
    assert result is not None
    assert "ATmega" in result["part"]


def test_unknown_part_returns_none():
    result = lookup_part("XYZZY99999_FAKE")
    assert result is None


def test_case_insensitive_matching():
    result = lookup_part("stm32f103")
    assert result is not None


# ---------------------------------------------------------------------------
# Tests: identify_components()
# ---------------------------------------------------------------------------

def test_identify_components_annotates_part_number():
    components = [
        Component(id="C0001", label="ic", confidence=0.8, bbox=(0, 0, 30, 20), marking="STM32"),
        Component(id="C0002", label="regulator", confidence=0.7, bbox=(50, 0, 20, 15), marking="LM1117"),
    ]
    result = identify_components(components)
    assert result[0].part_number != ""
    assert result[1].part_number != ""


def test_identify_components_skips_empty_markings():
    components = [
        Component(id="C0001", label="ic", confidence=0.5, bbox=(0, 0, 10, 10), marking=""),
    ]
    result = identify_components(components)
    assert result[0].part_number == ""


def test_identify_components_does_not_overwrite_existing_part():
    components = [
        Component(
            id="C0001",
            label="ic",
            confidence=0.9,
            bbox=(0, 0, 10, 10),
            marking="ESP32",
            part_number="CUSTOM-PART-XYZ",
        ),
    ]
    result = identify_components(components)
    # Existing part_number must not be overwritten
    assert result[0].part_number == "CUSTOM-PART-XYZ"


def test_identify_components_returns_same_list():
    components = [
        Component(id="C0001", label="ic", confidence=0.8, bbox=(0, 0, 10, 10), marking="CH340"),
    ]
    returned = identify_components(components)
    assert returned is components


# ---------------------------------------------------------------------------
# Tests: learn_component()
# ---------------------------------------------------------------------------

class TestLearnComponent:
    """Tests for the learn_component() function and _load_learned_components()."""

    _NEW_PART = {
        "part": "TESTPART9999",
        "aliases": ["TESTPART", "TP9999"],
        "category": "test",
        "manufacturer": "Acme",
        "package": "DIP8",
        "datasheet": "https://example.com/testpart.pdf",
        "description": "Fictional test component",
    }

    def _patch_path(self, monkeypatch, tmp_path):
        """Redirect LEARNED_DB_PATH to a temp dir for isolation."""
        fake_path = tmp_path / "learned_components.json"
        monkeypatch.setattr(matcher_mod, "LEARNED_DB_PATH", fake_path)
        return fake_path

    def test_learn_component_adds_to_db(self, monkeypatch, tmp_path):
        """learn_component() must extend _COMPONENT_DB and _LOOKUP at runtime."""
        fake_path = self._patch_path(monkeypatch, tmp_path)

        initial_db_len = len(matcher_mod._COMPONENT_DB)
        matcher_mod.learn_component(self._NEW_PART, path=fake_path)

        assert len(matcher_mod._COMPONENT_DB) == initial_db_len + 1
        assert "TESTPART9999" in matcher_mod._LOOKUP
        assert "TESTPART" in matcher_mod._LOOKUP
        assert "TP9999" in matcher_mod._LOOKUP
        assert matcher_mod._LOOKUP["TESTPART9999"]["manufacturer"] == "Acme"

        # Clean up in-memory state so other tests are unaffected
        matcher_mod._COMPONENT_DB.pop()
        del matcher_mod._LOOKUP["TESTPART9999"]
        del matcher_mod._LOOKUP["TESTPART"]
        del matcher_mod._LOOKUP["TP9999"]

    def test_learn_component_persists_to_disk(self, monkeypatch, tmp_path):
        """learn_component() must write the entry to LEARNED_DB_PATH."""
        fake_path = self._patch_path(monkeypatch, tmp_path)

        entry = {**self._NEW_PART, "part": "DISKPART0001"}
        matcher_mod.learn_component(entry, path=fake_path)

        assert fake_path.exists(), "JSON file should be created on disk"
        saved = json.loads(fake_path.read_text())
        assert isinstance(saved, list)
        parts = [e["part"] for e in saved]
        assert "DISKPART0001" in parts

        # Subsequent call appends rather than overwrites
        entry2 = {**self._NEW_PART, "part": "DISKPART0002"}
        matcher_mod.learn_component(entry2, path=fake_path)
        saved2 = json.loads(fake_path.read_text())
        assert len(saved2) == 2

        # Clean up in-memory state
        for p in ("DISKPART0001", "DISKPART0002", "TESTPART", "TP9999"):
            matcher_mod._LOOKUP.pop(p, None)
        matcher_mod._COMPONENT_DB[:] = [
            e for e in matcher_mod._COMPONENT_DB
            if e.get("part") not in ("DISKPART0001", "DISKPART0002")
        ]

    def test_learn_component_validates_part_key(self, monkeypatch, tmp_path):
        """learn_component() must raise ValueError if 'part' is missing."""
        fake_path = self._patch_path(monkeypatch, tmp_path)

        import pytest
        with pytest.raises(ValueError, match="part"):
            matcher_mod.learn_component({"aliases": ["NOPE"]}, path=fake_path)

    def test_learned_components_loaded_on_import(self, monkeypatch, tmp_path):
        """_load_learned_components() must extend _COMPONENT_DB from disk."""
        fake_path = self._patch_path(monkeypatch, tmp_path)

        # Pre-populate the file as if a previous session had saved it
        pre_entry = {**self._NEW_PART, "part": "PRELOADED_PART"}
        fake_path.write_text(json.dumps([pre_entry]))

        initial_db_len = len(matcher_mod._COMPONENT_DB)
        matcher_mod._load_learned_components(path=fake_path)

        assert len(matcher_mod._COMPONENT_DB) == initial_db_len + 1
        assert "PRELOADED_PART" in matcher_mod._LOOKUP

        # Clean up
        matcher_mod._COMPONENT_DB[:] = [
            e for e in matcher_mod._COMPONENT_DB if e.get("part") != "PRELOADED_PART"
        ]
        matcher_mod._LOOKUP.pop("PRELOADED_PART", None)
        matcher_mod._LOOKUP.pop("TESTPART", None)
        matcher_mod._LOOKUP.pop("TP9999", None)

    def test_load_learned_components_invalid_json(self, tmp_path):
        """_load_learned_components() silently returns on bad JSON (lines 1950-1951)."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json !!!")
        db_len_before = len(matcher_mod._COMPONENT_DB)
        matcher_mod._load_learned_components(path=bad_file)
        assert len(matcher_mod._COMPONENT_DB) == db_len_before

    def test_load_learned_components_non_list_json(self, tmp_path):
        """_load_learned_components() silently returns when root is not a list (line 1953)."""
        bad_file = tmp_path / "nonlist.json"
        bad_file.write_text(json.dumps({"part": "OOPS"}))
        db_len_before = len(matcher_mod._COMPONENT_DB)
        matcher_mod._load_learned_components(path=bad_file)
        assert len(matcher_mod._COMPONENT_DB) == db_len_before

    def test_load_learned_components_skips_malformed_entries(self, tmp_path):
        """_load_learned_components() skips non-dict entries and entries missing 'part' (line 1956)."""
        good_part = "GOODPART_LOAD_TEST"
        entries = [
            "not_a_dict",           # non-dict — skipped
            {"aliases": ["X"]},    # dict but no 'part' key — skipped
            {"part": good_part},   # valid
        ]
        f = tmp_path / "mixed.json"
        f.write_text(json.dumps(entries))
        db_len_before = len(matcher_mod._COMPONENT_DB)
        matcher_mod._load_learned_components(path=f)
        assert len(matcher_mod._COMPONENT_DB) == db_len_before + 1
        assert good_part in matcher_mod._LOOKUP
        # Clean up
        matcher_mod._COMPONENT_DB[:] = [
            e for e in matcher_mod._COMPONENT_DB if e.get("part") != good_part
        ]
        matcher_mod._LOOKUP.pop(good_part, None)

    def test_load_learned_components_skips_duplicate_part(self, tmp_path):
        """_load_learned_components() skips parts already in _LOOKUP (line 1959)."""
        # Pick a part we know is already in the DB (e.g. ESP32-WROOM-32)
        existing_key = "ESP32-WROOM-32"
        assert existing_key in matcher_mod._LOOKUP, "precondition: part must be in _LOOKUP"
        entries = [{"part": existing_key}]
        f = tmp_path / "dup.json"
        f.write_text(json.dumps(entries))
        db_len_before = len(matcher_mod._COMPONENT_DB)
        matcher_mod._load_learned_components(path=f)
        # Nothing new should be appended
        assert len(matcher_mod._COMPONENT_DB) == db_len_before

    def test_learn_component_corrupted_existing_file(self, monkeypatch, tmp_path):
        """learn_component() resets to [] when existing file is corrupt JSON (lines 1995-1997)."""
        fake_path = self._patch_path(monkeypatch, tmp_path)
        # Write corrupt JSON so the read inside learn_component fails
        fake_path.write_text("NOT VALID JSON")

        entry = {**self._NEW_PART, "part": "CORRUPT_RECOVER"}
        matcher_mod.learn_component(entry, path=fake_path)

        # File should now contain exactly one entry (the new one)
        saved = json.loads(fake_path.read_text())
        assert isinstance(saved, list)
        assert len(saved) == 1
        assert saved[0]["part"] == "CORRUPT_RECOVER"

        # Clean up
        matcher_mod._COMPONENT_DB[:] = [
            e for e in matcher_mod._COMPONENT_DB if e.get("part") != "CORRUPT_RECOVER"
        ]
        matcher_mod._LOOKUP.pop("CORRUPT_RECOVER", None)
        matcher_mod._LOOKUP.pop("TESTPART", None)
        matcher_mod._LOOKUP.pop("TP9999", None)

    def test_learn_component_non_list_existing_file(self, monkeypatch, tmp_path):
        """learn_component() resets to [] when existing file contains non-list JSON (line 1995)."""
        fake_path = self._patch_path(monkeypatch, tmp_path)
        # Write a dict instead of a list
        fake_path.write_text(json.dumps({"part": "SOME_DICT"}))

        entry = {**self._NEW_PART, "part": "NONLIST_RECOVER"}
        matcher_mod.learn_component(entry, path=fake_path)

        saved = json.loads(fake_path.read_text())
        assert isinstance(saved, list)
        assert len(saved) == 1
        assert saved[0]["part"] == "NONLIST_RECOVER"

        # Clean up
        matcher_mod._COMPONENT_DB[:] = [
            e for e in matcher_mod._COMPONENT_DB if e.get("part") != "NONLIST_RECOVER"
        ]
        matcher_mod._LOOKUP.pop("NONLIST_RECOVER", None)
        matcher_mod._LOOKUP.pop("TESTPART", None)
        matcher_mod._LOOKUP.pop("TP9999", None)


# ---------------------------------------------------------------------------
# Tests: extended component coverage (automotive MCU / display / wireless / PMIC)
# ---------------------------------------------------------------------------

class TestExtendedComponentCoverage:
    """Verify the database includes the expanded component families."""

    def test_db_size_meets_target(self):
        """The component DB must have at least 180 hardcoded entries."""
        assert len(matcher_mod._COMPONENT_DB) >= 180

    # --- Automotive MCUs --------------------------------------------------

    def test_automotive_mcu_s32k144(self):
        result = lookup_part("S32K144")
        assert result is not None
        assert result["manufacturer"] == "NXP"
        assert result["category"] == "automotive_mcu"
        assert "Cortex-M4F" in result["security_intel"]["core"]

    def test_automotive_mcu_s32k3(self):
        result = lookup_part("S32K344")
        assert result is not None
        assert "Cortex-M7" in result["security_intel"]["core"]
        assert "HSE" in result["security_intel"]["readout_protection"]

    def test_automotive_mcu_tms570(self):
        result = lookup_part("TMS570LS3137")
        assert result is not None
        assert result["manufacturer"] == "Texas Instruments"
        assert "Cortex-R4F" in result["security_intel"]["core"]

    def test_automotive_mcu_aurix(self):
        result = lookup_part("TC275")
        assert result is not None
        assert result["manufacturer"] == "Infineon"
        assert "TriCore" in result["security_intel"]["core"]

    def test_automotive_mcu_renesas_rh850(self):
        result = lookup_part("R7F701649")
        assert result is not None
        assert result["manufacturer"] == "Renesas"

    # --- Display drivers --------------------------------------------------

    def test_display_st7789(self):
        result = lookup_part("ST7789")
        assert result is not None
        assert result["category"] == "display"
        assert result["manufacturer"] == "Sitronix"

    def test_display_ili9488(self):
        result = lookup_part("ILI9488")
        assert result is not None
        assert "Ilitek" == result["manufacturer"]

    def test_display_ssd1351_color_oled(self):
        result = lookup_part("SSD1351")
        assert result is not None
        assert "OLED" in result["description"]

    def test_display_ra8875(self):
        result = lookup_part("RA8875")
        assert result is not None
        assert "RAiO" == result["manufacturer"]

    def test_display_gc9a01_round(self):
        """GC9A01 is the round-display controller used in many smartwatches."""
        result = lookup_part("GC9A01")
        assert result is not None
        assert "round" in result["description"].lower() or "240" in result["description"]

    # --- Wireless ---------------------------------------------------------

    def test_wireless_esp32_c2(self):
        result = lookup_part("ESP32-C2")
        assert result is not None
        assert "RISC-V" in result["security_intel"]["core"]

    def test_wireless_esp32_p4(self):
        result = lookup_part("ESP32-P4")
        assert result is not None
        assert result["manufacturer"] == "Espressif"

    def test_wireless_nrf52833(self):
        result = lookup_part("nRF52833")
        assert result is not None
        assert "APPROTECT" in result["security_intel"]["readout_protection"]

    def test_wireless_efr32mg21_zigbee_thread(self):
        result = lookup_part("EFR32MG21")
        assert result is not None
        assert result["manufacturer"] == "Silicon Labs"
        assert "Secure Vault" in result["security_intel"]["readout_protection"]

    def test_wireless_bl602_riscv(self):
        result = lookup_part("BL602")
        assert result is not None
        assert "RISC-V" in result["security_intel"]["core"]

    # --- Power management -------------------------------------------------

    def test_power_tps62130_buck(self):
        result = lookup_part("TPS62130")
        assert result is not None
        assert result["category"] == "regulator"

    def test_power_tps65186_epaper(self):
        result = lookup_part("TPS65186")
        assert result is not None
        assert "e-paper" in result["description"].lower()

    def test_power_ltc4054_charger(self):
        result = lookup_part("LTC4054")
        assert result is not None
        assert result["category"] == "battery_charger"

    def test_power_max17048_fuel_gauge(self):
        result = lookup_part("MAX17048")
        assert result is not None
        assert result["category"] == "fuel_gauge"

    def test_power_mcp73831_charger(self):
        result = lookup_part("MCP73831")
        assert result is not None
        assert result["manufacturer"] == "Microchip"

    def test_power_bq24074_charger_with_path_management(self):
        result = lookup_part("BQ24074")
        assert result is not None
        assert "power-path" in result["description"].lower()

    # --- Identify-components flow with new entries ------------------------

    def test_identify_picks_up_new_part_aliases(self):
        components = [
            Component(id="C1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), marking="S32K144"),
            Component(id="C2", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), marking="ST7789"),
            Component(id="C3", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), marking="MAX17048"),
        ]
        identified = identify_components(components)
        assert all(c.part_number != "" for c in identified)
        assert identified[0].part_number == "S32K144"
        assert identified[1].part_number == "ST7789"
        assert identified[2].part_number == "MAX17048"

    def test_security_intel_present_on_new_mcus(self):
        """All new automotive MCU entries must include security_intel."""
        for part in ("S32K144", "S32K344", "TMS570LS3137", "TC275", "R7F701649"):
            entry = matcher_mod._LOOKUP[part.upper()]
            assert "security_intel" in entry
            assert "debug_interfaces" in entry["security_intel"]

    def test_no_duplicate_part_numbers(self):
        """No two DB entries should share the same part number."""
        parts = [e["part"].upper() for e in matcher_mod._COMPONENT_DB]
        assert len(parts) == len(set(parts)), "duplicate part numbers in _COMPONENT_DB"
