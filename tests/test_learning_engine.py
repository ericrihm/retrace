"""Tests for retrace.learning.engine — persistent knowledge store."""

from __future__ import annotations

import json
from pathlib import Path

from retrace.learning.engine import (
    _load_knowledge,
    _save_knowledge,
    generate_report,
    queue_for_sourcing,
    record_detection,
    top_components,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _knowledge_path(tmp_path: Path) -> Path:
    return tmp_path / "knowledge.json"


# ---------------------------------------------------------------------------
# _load_knowledge
# ---------------------------------------------------------------------------

class TestLoadKnowledge:
    def test_creates_default_when_missing(self, tmp_path):
        path = _knowledge_path(tmp_path)
        data = _load_knowledge(path)
        assert data["version"] == "1.0"
        assert "component_frequency" in data
        assert "board_sightings" in data
        assert "sourcing_queue" in data
        assert data["sessions"] == 0

    def test_loads_existing_file(self, tmp_path):
        path = _knowledge_path(tmp_path)
        existing = {"version": "1.0", "component_frequency": {"STM32": 3}, "sessions": 5}
        path.write_text(json.dumps(existing))
        data = _load_knowledge(path)
        assert data["component_frequency"]["STM32"] == 3
        assert data["sessions"] == 5

    def test_returns_default_on_corrupt_json(self, tmp_path):
        path = _knowledge_path(tmp_path)
        path.write_text("NOT VALID JSON {{{")
        data = _load_knowledge(path)
        assert data["version"] == "1.0"
        assert data["sessions"] == 0

    def test_default_has_created_at(self, tmp_path):
        path = _knowledge_path(tmp_path)
        data = _load_knowledge(path)
        assert "created_at" in data


# ---------------------------------------------------------------------------
# _save_knowledge
# ---------------------------------------------------------------------------

class TestSaveKnowledge:
    def test_writes_json_file(self, tmp_path):
        path = _knowledge_path(tmp_path)
        _save_knowledge({"version": "1.0", "sessions": 1}, path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["sessions"] == 1

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "knowledge.json"
        _save_knowledge({"version": "1.0"}, path)
        assert path.exists()

    def test_overwrites_existing(self, tmp_path):
        path = _knowledge_path(tmp_path)
        _save_knowledge({"sessions": 1}, path)
        _save_knowledge({"sessions": 99}, path)
        data = json.loads(path.read_text())
        assert data["sessions"] == 99


# ---------------------------------------------------------------------------
# record_detection
# ---------------------------------------------------------------------------

class TestRecordDetection:
    def test_increments_frequency(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("STM32F103", path=path)
        record_detection("STM32F103", path=path)
        data = _load_knowledge(path)
        assert data["component_frequency"]["STM32F103"] == 2

    def test_tracks_board_sightings(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("NE555", board_image="/images/board1.jpg", path=path)
        record_detection("NE555", board_image="/images/board2.jpg", path=path)
        data = _load_knowledge(path)
        assert "/images/board1.jpg" in data["board_sightings"]["NE555"]
        assert "/images/board2.jpg" in data["board_sightings"]["NE555"]

    def test_deduplicates_board_sightings(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("LM358", board_image="/img/board.jpg", path=path)
        record_detection("LM358", board_image="/img/board.jpg", path=path)
        data = _load_knowledge(path)
        assert len(data["board_sightings"]["LM358"]) == 1

    def test_increments_sessions(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("A", path=path)
        record_detection("B", path=path)
        data = _load_knowledge(path)
        assert data["sessions"] == 2

    def test_sets_last_updated(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("X", path=path)
        data = _load_knowledge(path)
        assert "last_updated" in data

    def test_no_board_image_no_sightings(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("Y", path=path)
        data = _load_knowledge(path)
        assert "Y" not in data.get("board_sightings", {})


# ---------------------------------------------------------------------------
# queue_for_sourcing
# ---------------------------------------------------------------------------

class TestQueueForSourcing:
    def test_adds_item_to_queue(self, tmp_path):
        path = _knowledge_path(tmp_path)
        queue_for_sourcing("STM32", reason="High frequency", path=path)
        data = _load_knowledge(path)
        assert len(data["sourcing_queue"]) == 1
        item = data["sourcing_queue"][0]
        assert item["part"] == "STM32"
        assert item["reason"] == "High frequency"

    def test_deduplicates_queue(self, tmp_path):
        path = _knowledge_path(tmp_path)
        queue_for_sourcing("STM32", path=path)
        queue_for_sourcing("STM32", path=path)
        data = _load_knowledge(path)
        assert len(data["sourcing_queue"]) == 1

    def test_multiple_unique_parts(self, tmp_path):
        path = _knowledge_path(tmp_path)
        queue_for_sourcing("STM32", path=path)
        queue_for_sourcing("ESP32", path=path)
        data = _load_knowledge(path)
        assert len(data["sourcing_queue"]) == 2

    def test_added_at_timestamp(self, tmp_path):
        path = _knowledge_path(tmp_path)
        queue_for_sourcing("PART", path=path)
        data = _load_knowledge(path)
        assert "added_at" in data["sourcing_queue"][0]


# ---------------------------------------------------------------------------
# top_components
# ---------------------------------------------------------------------------

class TestTopComponents:
    def test_returns_sorted_by_frequency(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("A", path=path)
        record_detection("B", path=path)
        record_detection("B", path=path)
        record_detection("C", path=path)
        record_detection("C", path=path)
        record_detection("C", path=path)
        results = top_components(n=3, path=path)
        parts = [r[0] for r in results]
        assert parts[0] == "C"
        assert parts[1] == "B"
        assert parts[2] == "A"

    def test_respects_n_limit(self, tmp_path):
        path = _knowledge_path(tmp_path)
        for part in ["A", "B", "C", "D", "E"]:
            record_detection(part, path=path)
        results = top_components(n=2, path=path)
        assert len(results) <= 2

    def test_empty_store_returns_empty_list(self, tmp_path):
        path = _knowledge_path(tmp_path)
        results = top_components(path=path)
        assert results == []

    def test_returns_tuples_of_str_and_int(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("X", path=path)
        results = top_components(n=1, path=path)
        assert len(results) == 1
        part, count = results[0]
        assert isinstance(part, str)
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_returns_string(self, tmp_path):
        path = _knowledge_path(tmp_path)
        report = generate_report(path=path)
        assert isinstance(report, str)

    def test_contains_header(self, tmp_path):
        path = _knowledge_path(tmp_path)
        report = generate_report(path=path)
        assert "re:trace Learning Engine Report" in report

    def test_shows_sessions_count(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("X", path=path)
        record_detection("Y", path=path)
        report = generate_report(path=path)
        assert "2" in report

    def test_shows_top_components(self, tmp_path):
        path = _knowledge_path(tmp_path)
        record_detection("STM32F103", path=path)
        report = generate_report(path=path)
        assert "STM32F103" in report

    def test_shows_sourcing_queue(self, tmp_path):
        path = _knowledge_path(tmp_path)
        queue_for_sourcing("ESP32", reason="popular", path=path)
        report = generate_report(path=path)
        assert "ESP32" in report

    def test_no_data_message(self, tmp_path):
        path = _knowledge_path(tmp_path)
        report = generate_report(path=path)
        assert "No data yet" in report

    def test_separator_lines_present(self, tmp_path):
        path = _knowledge_path(tmp_path)
        report = generate_report(path=path)
        assert "=" * 10 in report
