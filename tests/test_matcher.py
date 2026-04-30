"""Tests for the component identification matcher."""

from __future__ import annotations

import json

from retrace.core.pipeline import Component
from retrace.identification.matcher import identify_components, lookup_part
import retrace.identification.matcher as matcher_mod


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
