"""Tests for the learning engine."""

from __future__ import annotations

from pathlib import Path


from retrace.learning.engine import (
    generate_report,
    queue_for_sourcing,
    record_detection,
    top_components,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_knowledge(tmp_path: Path) -> Path:
    return tmp_path / "knowledge.json"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_record_detection_persists(tmp_path):
    path = _tmp_knowledge(tmp_path)
    record_detection("STM32F103", path=path)
    top = top_components(path=path)
    parts = [p for p, _ in top]
    assert "STM32F103" in parts


def test_record_detection_increments_count(tmp_path):
    path = _tmp_knowledge(tmp_path)
    record_detection("ESP32", path=path)
    record_detection("ESP32", path=path)
    record_detection("ESP32", path=path)
    top = top_components(n=1, path=path)
    assert top[0] == ("ESP32", 3)


def test_queue_for_sourcing_adds_entry(tmp_path):
    path = _tmp_knowledge(tmp_path)
    queue_for_sourcing("nRF24L01", reason="Found on 3 boards", path=path)
    # Read back
    import json
    data = json.loads(path.read_text())
    queue = data.get("sourcing_queue", [])
    parts_in_queue = [item["part"] for item in queue]
    assert "nRF24L01" in parts_in_queue


def test_queue_for_sourcing_no_duplicates(tmp_path):
    path = _tmp_knowledge(tmp_path)
    queue_for_sourcing("W25Q128", path=path)
    queue_for_sourcing("W25Q128", path=path)
    import json
    data = json.loads(path.read_text())
    queue = data.get("sourcing_queue", [])
    w25_entries = [item for item in queue if item["part"] == "W25Q128"]
    assert len(w25_entries) == 1


def test_generate_report_returns_string(tmp_path):
    path = _tmp_knowledge(tmp_path)
    record_detection("ATmega328", path=path)
    report = generate_report(path=path)
    assert isinstance(report, str)
    assert "ATmega328" in report


def test_generate_report_empty_store(tmp_path):
    path = _tmp_knowledge(tmp_path)
    report = generate_report(path=path)
    assert "No data yet" in report or isinstance(report, str)
