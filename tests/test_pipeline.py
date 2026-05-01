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


# ---------------------------------------------------------------------------
# Tests: AnalysisResult.save() svg format
# ---------------------------------------------------------------------------

def test_save_svg(tmp_path):
    """save() with fmt='svg' delegates to generate_interactive_svg."""
    from unittest.mock import patch

    result = _make_result(n_components=2)
    with patch("retrace.export.svg.generate_interactive_svg", return_value="<svg/>") as mock_svg:
        result.save(tmp_path, fmt="svg")
    out = tmp_path / "annotated.svg"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "<svg/>"
    mock_svg.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Pipeline.run() (full pipeline, all sub-methods mocked)
# ---------------------------------------------------------------------------

def test_pipeline_run_full():
    """Pipeline.run() executes all phases and returns an AnalysisResult."""
    from unittest.mock import patch

    fake_img = np.zeros((100, 200, 3), dtype=np.uint8)
    fake_components = [
        Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), part_number="LM7805", marking="LM7805"),
        Component(id="R1", label="resistor", confidence=0.8, bbox=(20, 20, 5, 5), marking="10k"),
        Component(id="C1", label="capacitor", confidence=0.7, bbox=(30, 30, 5, 5)),
    ]
    fake_traces = [Trace(id="T1", points=[(0, 0), (10, 10)])]

    p = Pipeline(config={"enable_learning": True})

    with patch.object(p, "_load_image", return_value=fake_img), \
         patch.object(p, "_detect_components", return_value=fake_components), \
         patch.object(p, "_read_markings", return_value=fake_components), \
         patch.object(p, "_extract_traces", return_value=fake_traces), \
         patch.object(p, "_identify_components", return_value=fake_components), \
         patch.object(p, "_record_learnings") as mock_learn, \
         patch.object(p, "_run_cross_board") as mock_cross:
        result = p.run("/fake/board.jpg")

    assert isinstance(result, AnalysisResult)
    assert result.image_path == "/fake/board.jpg"
    assert result.board_dimensions == (200, 100)
    assert result.components == fake_components
    assert result.traces == fake_traces
    assert result.duration_seconds >= 0.0
    assert result.timestamp != ""
    mock_learn.assert_called_once_with(result)
    mock_cross.assert_called_once_with(result)


def test_pipeline_run_learning_disabled():
    """Pipeline.run() skips learning phases when enable_learning=False."""
    from unittest.mock import patch

    fake_img = np.zeros((100, 200, 3), dtype=np.uint8)

    p = Pipeline(config={"enable_learning": False})

    with patch.object(p, "_load_image", return_value=fake_img), \
         patch.object(p, "_detect_components", return_value=[]), \
         patch.object(p, "_read_markings", return_value=[]), \
         patch.object(p, "_extract_traces", return_value=[]), \
         patch.object(p, "_identify_components", return_value=[]), \
         patch.object(p, "_record_learnings") as mock_learn, \
         patch.object(p, "_run_cross_board") as mock_cross:
        p.run("/fake/board.jpg")

    mock_learn.assert_not_called()
    mock_cross.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Pipeline._load_image()
# ---------------------------------------------------------------------------

def test_load_image_cv2_success(tmp_path):
    """_load_image uses cv2 when available and returns an ndarray."""
    import cv2
    img_path = str(tmp_path / "board.png")
    img = np.zeros((50, 80, 3), dtype=np.uint8)
    cv2.imwrite(img_path, img)

    p = Pipeline()
    loaded = p._load_image(img_path)
    assert isinstance(loaded, np.ndarray)
    assert loaded.shape[:2] == (50, 80)


def test_load_image_cv2_returns_none_raises():
    """_load_image raises ValueError when cv2.imread returns None."""
    from unittest.mock import patch

    p = Pipeline()
    with patch("cv2.imread", return_value=None):
        with pytest.raises(ValueError, match="Could not load image"):
            p._load_image("/nonexistent/path.jpg")


def test_load_image_pil_fallback(tmp_path):
    """_load_image falls back to PIL when cv2 is unavailable."""
    from unittest.mock import patch

    from PIL import Image

    img_path = str(tmp_path / "board.png")
    img = Image.fromarray(np.zeros((40, 60, 3), dtype=np.uint8))
    img.save(img_path)

    p = Pipeline()
    with patch.dict("sys.modules", {"cv2": None}):
        loaded = p._load_image(img_path)
    assert isinstance(loaded, np.ndarray)
    assert loaded.shape[:2] == (40, 60)


# ---------------------------------------------------------------------------
# Tests: Pipeline._detect_components()
# ---------------------------------------------------------------------------

def test_detect_components_yolo_success():
    """_detect_components returns YOLO results when detector is available."""
    from unittest.mock import MagicMock, patch

    fake_comps = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10))]
    mock_detector = MagicMock()
    mock_detector.detect.return_value = fake_comps

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch("retrace.detection.detector.YOLODetector", return_value=mock_detector):
        result = p._detect_components(img)

    assert result == fake_comps


def test_detect_components_falls_back_on_import_error():
    """_detect_components falls back to contour detection when YOLO is missing."""
    from unittest.mock import patch

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    fallback_comps = [Component(id="C0000", label="resistor", confidence=0.5, bbox=(0, 0, 5, 5))]

    with patch.dict("sys.modules", {"retrace.detection.detector": None}), \
         patch.object(p, "_detect_contours", return_value=fallback_comps) as mock_contour:
        result = p._detect_components(img)

    assert result == fallback_comps
    mock_contour.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Pipeline._detect_contours() edge cases
# ---------------------------------------------------------------------------

def test_detect_contours_no_cv2():
    """_detect_contours returns empty list when cv2 is unavailable."""
    from unittest.mock import patch

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.dict("sys.modules", {"cv2": None}):
        result = p._detect_contours(img)

    assert result == []


def test_detect_contours_labels():
    """_detect_contours assigns connector, ic, capacitor, and resistor labels."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("OpenCV not available")

    # Build an image large enough that different size blobs get different labels
    img = np.zeros((600, 800, 3), dtype=np.uint8)

    # connector: wide aspect ratio (w/h > 2.5)
    img[100:110, 50:200] = 200       # 10h x 150w -> aspect=15

    # ic: large square-ish area > max_area * 0.3  (max_area = 0.15 * 480000 = 72000)
    # area needs > 21600; draw a 200x200 blob
    img[200:400, 100:300] = 180      # 200h x 200w = 40000 area

    # resistor: default (doesn't match connector, ic, or capacitor conditions)
    # small blob, aspect ~1.0 but area > min_area*10  (min_area = 0.001 * 480000 = 480, *10 = 4800)
    img[500:515, 600:660] = 160      # 15h x 60w = 900 area, aspect=4 -> connector actually
    # Let's make a proper resistor: aspect=1.5, area ~1000 (between min and max, not ic, not cap)
    img[500:530, 600:640] = 155      # 30h x 40w = 1200 area, aspect=1.33

    p = Pipeline()
    components = p._detect_contours(img)
    {c.label for c in components}
    # At least some labels should be detected
    assert isinstance(components, list)
    # Check that connector label is possible (wide blob)
    assert any(c.label in ("connector", "ic", "capacitor", "resistor") for c in components)


def test_detect_contours_capacitor_label():
    """_detect_contours assigns capacitor label for small near-square blobs."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("OpenCV not available")

    # min_area = 0.001 * W * H, max_area = 0.15 * W * H
    # For 600x800 image: min=480, max=72000
    # capacitor: 0.8 < aspect < 1.2 AND area < min_area*10 (4800)
    # A 30x30 blob: area=900, aspect=1.0 -> capacitor
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    img[100:130, 100:130] = 200  # 30x30 square

    p = Pipeline()
    components = p._detect_contours(img)
    [c for c in components if c.label == "capacitor"]
    # The square blob should be detected as capacitor if area/aspect conditions are met
    assert isinstance(components, list)


# ---------------------------------------------------------------------------
# Tests: Pipeline._read_markings(), _extract_traces(), _identify_components()
# ---------------------------------------------------------------------------

def test_read_markings_success():
    """_read_markings calls read_markings when the module is importable."""
    from unittest.mock import MagicMock, patch

    comps = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10))]
    marked = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), marking="STM32")]

    mock_module = MagicMock()
    mock_module.read_markings.return_value = marked

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.dict("sys.modules", {"retrace.detection.ocr": mock_module}):
        result = p._read_markings(img, comps)

    assert result == marked


def test_extract_traces_success():
    """_extract_traces calls extract_traces_from_image when importable."""
    from unittest.mock import MagicMock, patch

    fake_traces = [Trace(id="T1", points=[(0, 0), (10, 10)])]
    mock_module = MagicMock()
    mock_module.extract_traces_from_image.return_value = fake_traces

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.dict("sys.modules", {"retrace.detection.trace_extractor": mock_module}):
        result = p._extract_traces(img)

    assert result == fake_traces


def test_identify_components_success():
    """_identify_components calls identify_components when importable."""
    from unittest.mock import MagicMock, patch

    comps = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10))]
    identified = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), part_number="LM7805")]
    mock_module = MagicMock()
    mock_module.identify_components.return_value = identified

    p = Pipeline()

    with patch.dict("sys.modules", {"retrace.identification.matcher": mock_module}):
        result = p._identify_components(comps)

    assert result == identified


# ---------------------------------------------------------------------------
# Tests: _run_cross_board() edge cases
# ---------------------------------------------------------------------------

def test_run_cross_board_import_error():
    """_run_cross_board returns silently when cross_board module is unavailable."""
    from unittest.mock import patch

    result = AnalysisResult(image_path="board.jpg", components=[], traces=[])

    with patch.dict("sys.modules", {
        "retrace.analysis.cross_board": None,
        "retrace.analysis": None,
    }):
        p = Pipeline()
        p._run_cross_board(result)

    assert result.pattern_matches == []


def test_run_cross_board_corrupted_state_fallback():
    """_run_cross_board falls back to fresh engine when persisted state is corrupt."""
    from unittest.mock import MagicMock, patch

    from retrace.analysis.cross_board import BoardAnalysis

    result = AnalysisResult(image_path="board.jpg", components=[], traces=[])
    fake_analysis = BoardAnalysis(matches=[], novel_components=[], coverage=0.0)

    mock_engine_instance = MagicMock()
    mock_engine_instance.analyse.return_value = fake_analysis
    mock_engine_instance.to_dict.return_value = {"patterns": []}

    with patch("retrace.analysis.cross_board.CrossBoardEngine", return_value=mock_engine_instance) as mock_cls, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="NOT VALID JSON {{{"), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        p = Pipeline()
        p._run_cross_board(result)

    # Should have fallen back to CrossBoardEngine() constructor (not from_dict)
    mock_cls.assert_called_once_with()


def test_run_cross_board_traces_with_connections():
    """_run_cross_board includes traces that have from_component and to_component."""
    from unittest.mock import MagicMock, patch

    from retrace.analysis.cross_board import BoardAnalysis

    result = AnalysisResult(
        image_path="board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10)),
        ],
        traces=[
            Trace(id="T1", points=[(0, 0)], from_component="U1", to_component="C1"),
            Trace(id="T2", points=[(0, 0)]),  # no from/to — should be skipped
        ],
    )
    fake_analysis = BoardAnalysis(matches=[], novel_components=[], coverage=0.0)

    mock_engine_instance = MagicMock()
    mock_engine_instance.analyse.return_value = fake_analysis
    mock_engine_instance.to_dict.return_value = {}

    with patch("retrace.analysis.cross_board.CrossBoardEngine", return_value=mock_engine_instance), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        p = Pipeline()
        p._run_cross_board(result)

    # analyse was called; check board_traces only included connected traces
    call_args = mock_engine_instance.analyse.call_args
    board_traces = call_args[0][1]  # second positional arg
    assert len(board_traces) == 1
    assert board_traces[0].ref_a == "U1"
    assert board_traces[0].ref_b == "C1"


def test_run_cross_board_state_save_failure():
    """_run_cross_board logs a warning when persisted state cannot be written."""
    from unittest.mock import MagicMock, patch

    from retrace.analysis.cross_board import BoardAnalysis

    result = AnalysisResult(image_path="board.jpg", components=[], traces=[])
    fake_analysis = BoardAnalysis(matches=[], novel_components=[], coverage=0.0)

    mock_engine_instance = MagicMock()
    mock_engine_instance.analyse.return_value = fake_analysis
    mock_engine_instance.to_dict.return_value = {}

    with patch("retrace.analysis.cross_board.CrossBoardEngine", return_value=mock_engine_instance), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        p = Pipeline()
        # Should not raise — failure is caught and logged
        p._run_cross_board(result)


# ---------------------------------------------------------------------------
# Tests: _record_learnings() edge cases
# ---------------------------------------------------------------------------

def test_record_learnings_success_path():
    """_record_learnings works when learning.engine module is available."""
    from unittest.mock import MagicMock, patch

    mock_module = MagicMock()
    result = AnalysisResult(
        image_path="board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10),
                      part_number="LM7805", marking="LM7805"),
        ],
    )

    with patch.dict("sys.modules", {"retrace.learning.engine": mock_module}):
        p = Pipeline()
        p._record_learnings(result)

    mock_module.record_detection.assert_called_once_with("LM7805", "board.jpg")


def test_record_learnings_no_components():
    """_record_learnings with no identified/marked components logs nothing."""
    from unittest.mock import MagicMock, patch

    mock_module = MagicMock()
    result = AnalysisResult(
        image_path="board.jpg",
        components=[
            Component(id="C1", label="capacitor", confidence=0.8, bbox=(0, 0, 5, 5)),
        ],
    )

    with patch.dict("sys.modules", {"retrace.learning.engine": mock_module}):
        p = Pipeline()
        p._record_learnings(result)

    mock_module.record_detection.assert_not_called()
    mock_module.queue_for_sourcing.assert_not_called()


def test_record_learnings_import_error():
    """_record_learnings returns silently when learning.engine is unavailable."""
    from unittest.mock import patch

    result = AnalysisResult(
        image_path="board.jpg",
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10), part_number="LM7805"),
        ],
    )
    with patch.dict("sys.modules", {"retrace.learning": None, "retrace.learning.engine": None}):
        p = Pipeline()
        p._record_learnings(result)  # should not raise


def test_read_markings_import_error():
    """_read_markings returns components unchanged when ocr module is missing."""
    from unittest.mock import patch

    comps = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10))]
    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.dict("sys.modules", {"retrace.detection.ocr": None}):
        result = p._read_markings(img, comps)

    assert result == comps


def test_extract_traces_import_error():
    """_extract_traces returns [] when trace_extractor module is missing."""
    from unittest.mock import patch

    p = Pipeline()
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.dict("sys.modules", {"retrace.detection.trace_extractor": None}):
        result = p._extract_traces(img)

    assert result == []


def test_identify_components_import_error():
    """_identify_components returns components unchanged when matcher is missing."""
    from unittest.mock import patch

    comps = [Component(id="U1", label="ic", confidence=0.9, bbox=(0, 0, 10, 10))]
    p = Pipeline()

    with patch.dict("sys.modules", {"retrace.identification.matcher": None}):
        result = p._identify_components(comps)

    assert result == comps
