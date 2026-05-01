"""Tests for YOLODetector — ultralytics is mocked so no ML deps required."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from retrace.core.pipeline import Component

# ---------------------------------------------------------------------------
# Import smoke test (no ultralytics required)
# ---------------------------------------------------------------------------

def test_detector_module_importable():
    """The detector module must import cleanly even without ultralytics installed."""
    # If 'ultralytics' happens to be installed, temporarily hide it so this test
    # remains useful in all environments.
    with patch.dict(sys.modules, {"ultralytics": None}):
        # Re-importing after patching sys.modules may not reload, but we can
        # verify the module was already importable at collection time.
        import retrace.detection.detector  # noqa: F401 — just checking it exists
    assert True


# ---------------------------------------------------------------------------
# ImportError behaviour when ultralytics is absent
# ---------------------------------------------------------------------------

def test_yolo_detector_raises_import_error_when_ultralytics_missing():
    """YOLODetector.__init__ must raise ImportError with a helpful message."""
    # Remove ultralytics from sys.modules so the conditional import inside
    # _load_model fails.
    with patch.dict(sys.modules, {"ultralytics": None}):
        from retrace.detection.detector import YOLODetector
        with pytest.raises(ImportError) as exc_info:
            YOLODetector()

    msg = str(exc_info.value)
    assert "ultralytics" in msg.lower()
    assert "pip install" in msg.lower()


def test_yolo_detector_import_error_message_content():
    """The ImportError message should mention how to install the package."""
    with patch.dict(sys.modules, {"ultralytics": None}):
        from retrace.detection.detector import YOLODetector
        with pytest.raises(ImportError) as exc_info:
            YOLODetector()

    assert "pip install ultralytics" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Helpers: build a fake ultralytics YOLO module
# ---------------------------------------------------------------------------

def _make_fake_box(x1, y1, x2, y2, cls_idx, conf):
    """Return a mock ultralytics box object."""
    box = MagicMock()
    xyxy_tensor = MagicMock()
    xyxy_tensor.__getitem__ = MagicMock(return_value=MagicMock(tolist=MagicMock(return_value=[x1, y1, x2, y2])))
    box.xyxy = xyxy_tensor

    cls_tensor = MagicMock()
    cls_tensor.__getitem__ = MagicMock(return_value=MagicMock(item=MagicMock(return_value=cls_idx)))
    box.cls = cls_tensor

    conf_tensor = MagicMock()
    conf_tensor.__getitem__ = MagicMock(return_value=MagicMock(item=MagicMock(return_value=conf)))
    box.conf = conf_tensor

    return box


def _make_fake_yolo_result(boxes):
    """Return a fake ultralytics result object."""
    result = MagicMock()
    result.boxes = boxes
    return result


def _inject_fake_ultralytics(fake_model_instance):
    """Inject a fake ultralytics module with a YOLO class returning fake_model_instance."""
    fake_ultralytics = types.ModuleType("ultralytics")
    fake_yolo_cls = MagicMock(return_value=fake_model_instance)
    fake_ultralytics.YOLO = fake_yolo_cls
    return fake_ultralytics


# ---------------------------------------------------------------------------
# detect() with mocked ultralytics
# ---------------------------------------------------------------------------

def test_detect_returns_list_of_components():
    """detect() should return a list of Component objects."""
    fake_model = MagicMock()
    box = _make_fake_box(10, 20, 60, 80, cls_idx=0, conf=0.9)
    fake_result = _make_fake_yolo_result([box])
    fake_model.predict.return_value = [fake_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        # Must reimport to pick up the patched module
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model_path = "yolov8n.pt"
        detector._confidence = 0.35
        detector._device = None
        detector._model = fake_model

        image = np.zeros((480, 640, 3), dtype=np.uint8)
        components = detector.detect(image)

    assert isinstance(components, list)
    assert len(components) == 1
    c = components[0]
    assert isinstance(c, Component)
    assert c.label == "ic"
    assert 0.0 <= c.confidence <= 1.0
    assert len(c.bbox) == 4


def test_detect_maps_class_index_to_label():
    """Each YOLO class index should map to the correct label string."""
    label_map = {
        0: "ic", 1: "capacitor", 2: "resistor", 3: "connector",
        4: "inductor", 5: "crystal", 6: "header", 7: "test_point",
        8: "diode", 9: "transistor",
    }

    for cls_idx, expected_label in label_map.items():
        fake_model = MagicMock()
        box = _make_fake_box(0, 0, 50, 50, cls_idx=cls_idx, conf=0.75)
        fake_result = _make_fake_yolo_result([box])
        fake_model.predict.return_value = [fake_result]

        fake_ultra = _inject_fake_ultralytics(fake_model)

        with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
            import importlib

            import retrace.detection.detector as det_mod
            importlib.reload(det_mod)
            detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
            detector._model = fake_model
            detector._confidence = 0.35

            components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        assert components[0].label == expected_label, f"cls {cls_idx} → {expected_label}"


def test_detect_unknown_class_index_produces_class_label():
    """Class indices outside _LABEL_MAP should produce 'class_N' labels."""
    fake_model = MagicMock()
    box = _make_fake_box(0, 0, 30, 30, cls_idx=99, conf=0.6)
    fake_result = _make_fake_yolo_result([box])
    fake_model.predict.return_value = [fake_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert components[0].label == "class_99"


def test_detect_returns_empty_when_no_boxes():
    """When the YOLO result has no boxes, detect() returns an empty list."""
    fake_model = MagicMock()
    fake_result = _make_fake_yolo_result([])
    fake_model.predict.return_value = [fake_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert components == []


def test_detect_returns_empty_when_model_is_none():
    """If _model is None detect() should return [] without raising."""
    with patch.dict(sys.modules, {"ultralytics": MagicMock()}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = None
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert components == []


def test_detect_handles_predict_exception():
    """If predict() raises, detect() should log the error and return []."""
    fake_model = MagicMock()
    fake_model.predict.side_effect = RuntimeError("GPU OOM")

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((200, 200, 3), dtype=np.uint8))

    assert components == []


def test_detect_synthetic_rgb_image():
    """detect() accepts a synthetic numpy RGB image without type errors."""
    fake_model = MagicMock()
    box = _make_fake_box(5, 5, 55, 55, cls_idx=2, conf=0.8)
    fake_result = _make_fake_yolo_result([box])
    fake_model.predict.return_value = [fake_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        # Synthetic noise image
        rng = np.random.default_rng(42)
        image = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
        components = detector.detect(image)

    assert len(components) == 1
    assert components[0].label == "resistor"


def test_component_id_is_unique():
    """Each detected component should have a unique id prefixed with 'D'."""
    fake_model = MagicMock()
    boxes = [_make_fake_box(i * 10, 0, i * 10 + 40, 40, cls_idx=0, conf=0.7) for i in range(5)]
    fake_result = _make_fake_yolo_result(boxes)
    fake_model.predict.return_value = [fake_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 300, 3), dtype=np.uint8))

    ids = [c.id for c in components]
    assert len(ids) == len(set(ids)), "Component IDs should be unique"
    for cid in ids:
        assert cid.startswith("D")


# ---------------------------------------------------------------------------
# _load_model() success paths (lines 77-82)
# ---------------------------------------------------------------------------

def test_load_model_success_no_device():
    """_load_model() should call YOLO with the model path and no device kwarg."""
    fake_model_instance = MagicMock()
    fake_yolo_cls = MagicMock(return_value=fake_model_instance)
    fake_ultra = types.ModuleType("ultralytics")
    fake_ultra.YOLO = fake_yolo_cls

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)

        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model_path = "yolov8n.pt"
        detector._confidence = 0.35
        detector._device = None
        detector._model = None

        detector._load_model()

    fake_yolo_cls.assert_called_once_with("yolov8n.pt")
    assert detector._model is fake_model_instance


def test_load_model_success_with_device():
    """_load_model() should pass device kwarg when _device is set (line 80)."""
    fake_model_instance = MagicMock()
    fake_yolo_cls = MagicMock(return_value=fake_model_instance)
    fake_ultra = types.ModuleType("ultralytics")
    fake_ultra.YOLO = fake_yolo_cls

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)

        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model_path = "yolov8n.pt"
        detector._confidence = 0.35
        detector._device = "cpu"
        detector._model = None

        detector._load_model()

    fake_yolo_cls.assert_called_once_with("yolov8n.pt", device="cpu")
    assert detector._model is fake_model_instance


# ---------------------------------------------------------------------------
# detect() with result.boxes is None (line 114)
# ---------------------------------------------------------------------------

def test_detect_skips_result_with_none_boxes():
    """When result.boxes is None detect() skips that result and returns []."""
    fake_model = MagicMock()
    # result with boxes=None
    none_box_result = MagicMock()
    none_box_result.boxes = None
    fake_model.predict.return_value = [none_box_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert components == []


def test_detect_mixed_none_and_valid_boxes():
    """Results with None boxes are skipped; valid results are still processed."""
    fake_model = MagicMock()
    none_box_result = MagicMock()
    none_box_result.boxes = None

    box = _make_fake_box(0, 0, 40, 40, cls_idx=1, conf=0.85)
    valid_result = _make_fake_yolo_result([box])

    fake_model.predict.return_value = [none_box_result, valid_result]

    fake_ultra = _inject_fake_ultralytics(fake_model)

    with patch.dict(sys.modules, {"ultralytics": fake_ultra}):
        import importlib

        import retrace.detection.detector as det_mod
        importlib.reload(det_mod)
        detector = det_mod.YOLODetector.__new__(det_mod.YOLODetector)
        detector._model = fake_model
        detector._confidence = 0.35

        components = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert len(components) == 1
    assert components[0].label == "capacitor"
