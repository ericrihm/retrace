"""Tests for the component identification matcher."""

from __future__ import annotations


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
