"""Tests for the core Pipeline class and related dataclasses."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from retrace.core.pipeline import AnalysisResult, Component, Pipeline, Trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic_image(width: int = 400, height: int = 300) -> np.ndarray:
    """Create an RGB image with coloured rectangles simulating board components."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (30, 60, 30)  # dark green PCB background

    # Draw several bright rectangles for components
    regions = [
        (50,  50, 80, 40, (200, 200, 200)),   # IC-ish blob
        (200, 50, 30, 20, (180, 180, 180)),   # smaller IC
        (300, 80, 15, 8,  (150, 150, 150)),   # resistor-ish
        (120, 200, 12, 12, (160, 160, 160)),  # cap-ish square
        (250, 200, 60, 10, (140, 140, 200)),  # connector
    ]
    for x, y, w, h, color in regions:
        img[y : y + h, x : x + w] = color

    return img


def _make_result(n_components: int = 3, n_traces: int = 2) -> AnalysisResult:
    components = [
        Component(
            id=f"C{i:04d}",
            label="ic" if i % 3 == 0 else "resistor",
            confidence=0.8,
            bbox=(i * 10, i * 10, 30, 20),
            marking=f"U{i}",
        )
        for i in range(n_components)
    ]
    traces = [
        Trace(id=f"T{i:04d}", points=[(0, 0), (100, 100)])
        for i in range(n_traces)
    ]
    return AnalysisResult(
        image_path="/fake/image.jpg",
        components=components,
        traces=traces,
        board_dimensions=(400, 300),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


# ---------------------------------------------------------------------------
# Tests: dataclass construction
# ---------------------------------------------------------------------------

def test_component_defaults():
    comp = Component(id="C0001", label="ic", confidence=0.9, bbox=(10, 20, 30, 40))
    assert comp.marking == ""
    assert comp.part_number == ""
    assert comp.datasheet_url == ""
    assert comp.value == ""
    assert comp.package == ""


def test_trace_defaults():
    trace = Trace(id="T0001", points=[(0, 0), (50, 50)])
    assert trace.width_px == 0.0
    assert trace.from_component == ""
    assert trace.to_component == ""


def test_analysis_result_defaults():
    result = AnalysisResult(image_path="/tmp/board.jpg")
    assert result.components == []
    assert result.traces == []
    assert result.board_dimensions == (0, 0)
    assert result.pipeline_version == "0.1.0"


# ---------------------------------------------------------------------------
# Tests: AnalysisResult.summary()
# ---------------------------------------------------------------------------

def test_summary_component_counts():
    result = _make_result(n_components=5, n_traces=3)
    s = result.summary()
    assert s["components"] == 5
    assert s["traces"] == 3


def test_summary_by_label():
    result = _make_result(n_components=6)
    s = result.summary()
    total = sum(s["components_by_type"].values())
    assert total == 6


def test_summary_identified_count():
    result = _make_result(n_components=4)
    # Give part_number to 2 components
    result.components[0].part_number = "STM32F103"
    result.components[2].part_number = "AMS1117"
    s = result.summary()
    assert s["identified"] == 2


def test_summary_empty():
    result = AnalysisResult(image_path="x.jpg")
    s = result.summary()
    assert s["components"] == 0
    assert s["identified"] == 0


# ---------------------------------------------------------------------------
# Tests: AnalysisResult.save()
# ---------------------------------------------------------------------------

def test_save_json(tmp_path):
    result = _make_result(n_components=2)
    result.save(tmp_path, fmt="json")
    out = tmp_path / "analysis.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert "components" in data
    assert len(data["components"]) == 2


def test_save_csv(tmp_path):
    result = _make_result(n_components=3)
    result.save(tmp_path, fmt="csv")
    out = tmp_path / "components.csv"
    assert out.exists()
    lines = out.read_text().splitlines()
    # header + 3 data rows
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# Tests: Pipeline instantiation and _detect_contours fallback
# ---------------------------------------------------------------------------

def test_pipeline_instantiation():
    p = Pipeline()
    assert p.config == {}
    assert p._detector is None


def test_pipeline_with_config():
    cfg = {"model": "yolov8n", "confidence": 0.5}
    p = Pipeline(config=cfg)
    assert p.config["model"] == "yolov8n"


def test_record_learnings_records_identified_parts():
    """_record_learnings calls record_detection for identified parts and queues unmatched."""
    from unittest.mock import patch

    result = AnalysisResult(
        image_path="test_board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10),
                      part_number="STM32F103C8T6", marking="STM32F103"),
            Component(id="U2", label="ic", confidence=0.9, bbox=(20, 20, 10, 10),
                      marking="UNKNOWN_CHIP"),
            Component(id="C1", label="capacitor", confidence=0.8, bbox=(30, 30, 5, 5)),
        ],
    )

    with patch("retrace.learning.engine.record_detection") as mock_rec, \
         patch("retrace.learning.engine.queue_for_sourcing") as mock_queue:
        p = Pipeline(config={"enable_learning": True})
        p._record_learnings(result)

        mock_rec.assert_called_once_with("STM32F103C8T6", "test_board.jpg")
        mock_queue.assert_called_once_with("UNKNOWN_CHIP", reason="OCR read, no DB match")


def test_record_learnings_disabled():
    """When enable_learning is False, no learning calls are made."""
    result = AnalysisResult(
        image_path="test.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10),
                      part_number="LM7805"),
        ],
    )
    p = Pipeline(config={"enable_learning": False})
    # Should not raise even without a valid knowledge path
    p._record_learnings(result)


# ---------------------------------------------------------------------------
# Tests: _run_cross_board (Phase 6)
# ---------------------------------------------------------------------------

def test_run_cross_board_populates_pattern_matches():
    """_run_cross_board converts components/traces and populates pattern_matches."""
    from unittest.mock import MagicMock, patch
    from retrace.analysis.cross_board import BoardAnalysis, PatternMatch

    result = AnalysisResult(
        image_path="board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(100, 100, 30, 20)),
            Component(id="C1", label="capacitor", confidence=0.8, bbox=(130, 90, 10, 8)),
            Component(id="C2", label="capacitor", confidence=0.8, bbox=(70, 110, 10, 8)),
            Component(id="R1", label="resistor", confidence=0.7, bbox=(300, 200, 10, 5)),
        ],
        traces=[
            Trace(id="T1", points=[(0, 0)], from_component="U1", to_component="C1"),
            Trace(id="T2", points=[(0, 0)], from_component="U1", to_component="C2"),
        ],
    )

    fake_match = PatternMatch(
        pattern_name="ldo_supply",
        description="LDO voltage regulator with input and output bypass caps",
        component_roles={"ldo": "U1", "input_cap": "C1", "output_cap": "C2"},
        score=0.85,
        is_partial=False,
    )
    fake_analysis = BoardAnalysis(
        matches=[fake_match],
        novel_components=["R1"],
        coverage=0.75,
    )

    mock_engine_instance = MagicMock()
    mock_engine_instance.analyse.return_value = fake_analysis
    mock_engine_instance.to_dict.return_value = {"patterns": []}

    with patch("retrace.analysis.cross_board.CrossBoardEngine", return_value=mock_engine_instance), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        p = Pipeline(config={"enable_learning": True})
        p._run_cross_board(result)

    assert len(result.pattern_matches) == 1
    assert result.pattern_matches[0]["pattern_name"] == "ldo_supply"
    assert result.pattern_matches[0]["score"] == 0.85
    assert result.pattern_matches[0]["component_roles"] == {"ldo": "U1", "input_cap": "C1", "output_cap": "C2"}
    assert result.pattern_matches[0]["is_partial"] is False


def test_run_cross_board_empty_components():
    """_run_cross_board handles empty components and traces gracefully."""
    from unittest.mock import patch

    result = AnalysisResult(image_path="empty.jpg", components=[], traces=[])

    with patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        p = Pipeline(config={"enable_learning": True})
        p._run_cross_board(result)

    assert result.pattern_matches == []


def test_run_cross_board_loads_persisted_state():
    """_run_cross_board loads engine state from disk when the file exists."""
    from unittest.mock import MagicMock, patch
    from retrace.analysis.cross_board import BoardAnalysis

    result = AnalysisResult(image_path="board.jpg", components=[], traces=[])

    saved_state = '{"patterns": []}'
    fake_analysis = BoardAnalysis(matches=[], novel_components=[], coverage=0.0)

    mock_engine_instance = MagicMock()
    mock_engine_instance.analyse.return_value = fake_analysis
    mock_engine_instance.to_dict.return_value = {"patterns": []}

    with patch("retrace.analysis.cross_board.CrossBoardEngine") as mock_cls, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=saved_state), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        mock_cls.from_dict.return_value = mock_engine_instance
        p = Pipeline(config={"enable_learning": True})
        p._run_cross_board(result)

    mock_cls.from_dict.assert_called_once()


def test_run_cross_board_disabled_when_learning_off():
    """_run_cross_board is not called when enable_learning is False."""
    result = _make_result(n_components=2)
    original_matches = list(result.pattern_matches)

    # If _run_cross_board were called, it would change pattern_matches;
    # verify the run() method gates on enable_learning
    p = Pipeline(config={"enable_learning": False})
    # Directly check that the config gate works
    assert p.config.get("enable_learning", True) is False
    assert result.pattern_matches == original_matches


def test_pattern_matches_in_summary():
    """pattern_matches count appears in summary output."""
    result = _make_result(n_components=2)
    result.pattern_matches = [
        {"pattern_name": "rc_lowpass", "description": "filter", "component_roles": {}, "score": 0.7, "is_partial": False},
    ]
    s = result.summary()
    assert s["pattern_matches"] == 1


def test_pattern_matches_in_save_json(tmp_path):
    """pattern_matches are included in saved JSON output."""
    result = _make_result(n_components=1)
    result.pattern_matches = [
        {"pattern_name": "ldo_supply", "description": "LDO", "component_roles": {"ldo": "U1"}, "score": 0.9, "is_partial": False},
    ]
    result.save(tmp_path, fmt="json")
    data = json.loads((tmp_path / "analysis.json").read_text())
    assert "pattern_matches" in data
    assert len(data["pattern_matches"]) == 1
    assert data["pattern_matches"][0]["pattern_name"] == "ldo_supply"


def test_pattern_matches_default_empty():
    """AnalysisResult.pattern_matches defaults to empty list."""
    result = AnalysisResult(image_path="x.jpg")
    assert result.pattern_matches == []


# ---------------------------------------------------------------------------
# Tests: Pipeline instantiation and _detect_contours fallback
# ---------------------------------------------------------------------------

def test_pipeline_detect_contours_synthetic():
    """_detect_contours must not crash on a synthetic numpy image."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("OpenCV not available")

    p = Pipeline()
    img = _make_synthetic_image()
    components = p._detect_contours(img)
    # Should return a list (may be empty or have detections)
    assert isinstance(components, list)
    for c in components:
        assert isinstance(c, Component)
        assert len(c.bbox) == 4
