"""Tests for src/retrace/detection/trace_extractor.py

Uses synthetic numpy images (drawn with OpenCV) to exercise the pipeline
without any ML, scikit-image, or other heavy dependencies.

The trace extractor has an internal fallback when skimage is not available
(_skeletonize falls back to morphological thinning), so we also verify
that mock works correctly.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import numpy as np
import pytest

from retrace.core.pipeline import Trace

# Guard: OpenCV is required for any test in this file
cv2 = pytest.importorskip("cv2", reason="OpenCV required for trace extractor tests")

from retrace.detection.trace_extractor import extract_traces_from_image  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic image helpers
# ---------------------------------------------------------------------------

def _blank_black_image(h: int = 100, w: int = 100) -> np.ndarray:
    """Return an all-black BGR image."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _copper_bgr() -> tuple[int, int, int]:
    """Return a BGR colour that falls within the HSV copper range (hue ~15)."""
    # HSV (15, 200, 200) → BGR
    hsv = np.array([[[15, 200, 200]]], dtype=np.uint8)
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return int(bgr[0, 0, 0]), int(bgr[0, 0, 1]), int(bgr[0, 0, 2])


def _image_with_horizontal_line(
    h: int = 100,
    w: int = 200,
    thickness: int = 6,
) -> np.ndarray:
    """BGR image with a thick horizontal copper-colored line across the middle."""
    img = _blank_black_image(h, w)
    color = _copper_bgr()
    mid = h // 2
    cv2.line(img, (10, mid), (w - 10, mid), color, thickness)
    return img


def _image_with_vertical_line(
    h: int = 200,
    w: int = 100,
    thickness: int = 6,
) -> np.ndarray:
    """BGR image with a thick vertical copper-colored line."""
    img = _blank_black_image(h, w)
    color = _copper_bgr()
    mid = w // 2
    cv2.line(img, (mid, 10), (mid, h - 10), color, thickness)
    return img


def _image_with_two_lines(h: int = 200, w: int = 200) -> np.ndarray:
    """BGR image with two separate copper-colored lines (two trace paths)."""
    img = _blank_black_image(h, w)
    color = _copper_bgr()
    # Horizontal line in top half
    cv2.line(img, (10, 50), (w - 10, 50), color, 6)
    # Horizontal line in bottom half (separated by gap)
    cv2.line(img, (10, 150), (w - 10, 150), color, 6)
    return img


def _image_with_copper_blob(h: int = 100, w: int = 100) -> np.ndarray:
    """A filled copper-colored rectangle (should produce at least one trace)."""
    img = _blank_black_image(h, w)
    color = _copper_bgr()
    cv2.rectangle(img, (20, 20), (80, 80), color, -1)
    return img


# ---------------------------------------------------------------------------
# Basic return-type & structure
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_list(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        assert isinstance(result, list)

    def test_list_elements_are_trace_objects(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        for item in result:
            assert isinstance(item, Trace)

    def test_trace_has_id(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        if result:
            assert isinstance(result[0].id, str)
            assert len(result[0].id) > 0

    def test_trace_id_starts_with_T(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        if result:
            assert result[0].id.startswith("T")

    def test_trace_has_points_list(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        if result:
            assert isinstance(result[0].points, list)

    def test_trace_points_are_tuples(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        if result:
            for pt in result[0].points:
                assert isinstance(pt, tuple)
                assert len(pt) == 2

    def test_trace_has_width_px(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        if result:
            assert isinstance(result[0].width_px, float)

    def test_trace_width_non_negative(self):
        img = _image_with_horizontal_line()
        result = extract_traces_from_image(img)
        for t in result:
            assert t.width_px >= 0.0

    def test_all_trace_ids_unique(self):
        img = _image_with_two_lines()
        result = extract_traces_from_image(img)
        ids = [t.id for t in result]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Blank / black image
# ---------------------------------------------------------------------------

class TestBlankImage:
    def test_black_image_returns_empty(self):
        img = _blank_black_image(100, 100)
        result = extract_traces_from_image(img)
        assert result == []

    def test_black_image_small_returns_empty(self):
        img = _blank_black_image(10, 10)
        result = extract_traces_from_image(img)
        assert result == []

    def test_black_image_large_returns_empty(self):
        img = _blank_black_image(500, 500)
        result = extract_traces_from_image(img)
        assert result == []

    def test_non_copper_colored_image_returns_empty(self):
        """Pure blue image — no copper tones — should yield no traces."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :, 0] = 200  # blue channel only
        result = extract_traces_from_image(img)
        assert result == []


# ---------------------------------------------------------------------------
# Synthetic copper line images produce traces
# ---------------------------------------------------------------------------

class TestCopperLines:
    def test_horizontal_line_produces_traces(self):
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        result = extract_traces_from_image(img)
        assert len(result) >= 1

    def test_vertical_line_produces_traces(self):
        img = _image_with_vertical_line(h=200, w=100, thickness=8)
        result = extract_traces_from_image(img)
        assert len(result) >= 1

    def test_horizontal_line_points_have_enough_length(self):
        """BFS traces must have >= 5 pixels (noise filter)."""
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        result = extract_traces_from_image(img)
        for t in result:
            assert len(t.points) >= 5

    def test_copper_blob_produces_at_least_one_trace(self):
        img = _image_with_copper_blob()
        result = extract_traces_from_image(img)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Small / edge-size images don't crash
# ---------------------------------------------------------------------------

class TestSmallImages:
    def test_1x1_image_no_crash(self):
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert isinstance(result, list)

    def test_1x1_black_image_returns_empty(self):
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert result == []

    def test_4x4_image_no_crash(self):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert isinstance(result, list)

    def test_1_pixel_wide_image_no_crash(self):
        img = np.zeros((100, 1, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert isinstance(result, list)

    def test_1_pixel_tall_image_no_crash(self):
        img = np.zeros((1, 100, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Empty / None guard
# ---------------------------------------------------------------------------

class TestEmptyImageGuard:
    def test_empty_ndarray_returns_empty_list(self):
        img = np.zeros((0, 0, 3), dtype=np.uint8)
        result = extract_traces_from_image(img)
        assert result == []

    def test_none_returns_empty_list(self):
        """The module guards img is None → return []."""
        result = extract_traces_from_image(None)  # type: ignore[arg-type]
        assert result == []


# ---------------------------------------------------------------------------
# Skeletonize fallback: mock skimage as unavailable
# ---------------------------------------------------------------------------

class TestSkeletonizeFallback:
    def test_skimage_unavailable_horizontal_line(self):
        """With skimage mocked away, the cv2 morphological fallback must work."""
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)

        # Make skimage.morphology import fail inside _skeletonize
        fake_modules = {k: v for k, v in sys.modules.items()}
        # Remove any cached skimage modules
        for key in list(fake_modules.keys()):
            if "skimage" in key:
                fake_modules.pop(key)

        with patch.dict(sys.modules, {"skimage": None, "skimage.morphology": None}):
            result = extract_traces_from_image(img)

        assert isinstance(result, list)

    def test_skimage_unavailable_black_image_still_empty(self):
        """With skimage absent, black images must still return empty."""
        img = _blank_black_image(100, 100)
        with patch.dict(sys.modules, {"skimage": None, "skimage.morphology": None}):
            result = extract_traces_from_image(img)
        assert result == []

    def test_skimage_raises_import_error_fallback_used(self):
        """Simulate ImportError inside _skeletonize by patching the skimage module
        to None (the module-level guard in _skeletonize catches ImportError)."""
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        with patch.dict(sys.modules, {"skimage.morphology": None}):
            result = extract_traces_from_image(img)
        # Should still succeed via morphological fallback
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# extract_traces (file-path API)
# ---------------------------------------------------------------------------

class TestExtractTracesFileAPI:
    """Tests for the file-path-based extract_traces() entry point."""

    def test_file_not_found_raises(self, tmp_path):
        """Nonexistent path raises FileNotFoundError."""
        from retrace.detection.trace_extractor import extract_traces
        missing = str(tmp_path / "no_such_file.png")
        with pytest.raises(FileNotFoundError, match="Image not found"):
            extract_traces(missing)

    def test_unreadable_file_raises_value_error(self, tmp_path):
        """A file that exists but cannot be decoded raises ValueError."""
        from retrace.detection.trace_extractor import extract_traces
        bad_file = tmp_path / "garbage.png"
        bad_file.write_bytes(b"this is not a valid image")
        with pytest.raises(ValueError, match="Could not decode image"):
            extract_traces(str(bad_file))

    def test_valid_image_returns_dict_structure(self, tmp_path):
        """A valid PNG image returns a dict with 'count' and 'traces' keys."""
        import cv2

        from retrace.detection.trace_extractor import extract_traces
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        img_path = str(tmp_path / "test.png")
        cv2.imwrite(img_path, img)
        result = extract_traces(img_path)
        assert isinstance(result, dict)
        assert "count" in result
        assert "traces" in result

    def test_valid_image_count_matches_traces(self, tmp_path):
        """count field matches len(traces) list."""
        import cv2

        from retrace.detection.trace_extractor import extract_traces
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        img_path = str(tmp_path / "test.png")
        cv2.imwrite(img_path, img)
        result = extract_traces(img_path)
        assert result["count"] == len(result["traces"])

    def test_valid_image_trace_dict_fields(self, tmp_path):
        """Each trace dict has id, points, width_px, from_component, to_component."""
        import cv2

        from retrace.detection.trace_extractor import extract_traces
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        img_path = str(tmp_path / "test.png")
        cv2.imwrite(img_path, img)
        result = extract_traces(img_path)
        for t in result["traces"]:
            assert "id" in t
            assert "points" in t
            assert "width_px" in t
            assert "from_component" in t
            assert "to_component" in t

    def test_black_image_returns_zero_count(self, tmp_path):
        """A black image produces count=0 and empty traces list."""
        import cv2

        from retrace.detection.trace_extractor import extract_traces
        img = _blank_black_image(100, 100)
        img_path = str(tmp_path / "black.png")
        cv2.imwrite(img_path, img)
        result = extract_traces(img_path)
        assert result["count"] == 0
        assert result["traces"] == []

    def test_path_object_accepted(self, tmp_path):
        """extract_traces accepts a Path object as well as a string."""

        import cv2

        from retrace.detection.trace_extractor import extract_traces
        img = _blank_black_image(50, 50)
        img_path = tmp_path / "path_obj.png"
        cv2.imwrite(str(img_path), img)
        result = extract_traces(img_path)  # Path object
        assert isinstance(result, dict)

    def test_cv2_unavailable_raises_import_error(self, tmp_path):
        """If cv2 is not installed, extract_traces raises ImportError with helpful message."""
        from retrace.detection.trace_extractor import extract_traces
        # Write a real file so we get past the existence check
        dummy = tmp_path / "dummy.png"
        dummy.write_bytes(b"\x89PNG\r\n")
        with patch.dict(sys.modules, {"cv2": None}):
            with pytest.raises(ImportError, match="OpenCV is required"):
                extract_traces(str(dummy))


# ---------------------------------------------------------------------------
# cv2 ImportError path in extract_traces_from_image
# ---------------------------------------------------------------------------

class TestCv2MissingInExtractFromImage:
    def test_cv2_unavailable_raises_import_error(self):
        """extract_traces_from_image raises ImportError with helpful message when cv2 absent."""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        with patch.dict(sys.modules, {"cv2": None}):
            with pytest.raises(ImportError, match="OpenCV is required"):
                extract_traces_from_image(img)


# ---------------------------------------------------------------------------
# Skimage happy path (mocked)
# ---------------------------------------------------------------------------

class TestSkeletonizeSkimagePath:
    def test_skimage_skeletonize_used_when_available(self):
        """When skimage IS importable, the skimage code path (lines 174-176) runs."""
        import types

        import cv2

        # Build a real binary mask from a copper image
        img = _image_with_horizontal_line(h=100, w=200, thickness=8)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lo = np.array([5, 60, 60], dtype=np.uint8)
        hi = np.array([25, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lo, hi)

        # Create a fake skimage.morphology module with a real skeletonize impl
        from retrace.detection.trace_extractor import _skeletonize

        (mask > 0).astype(np.uint8) * 255  # identity passthrough

        fake_morph = types.ModuleType("skimage.morphology")
        fake_morph.skeletonize = lambda binary: binary.astype(np.uint8)

        fake_skimage = types.ModuleType("skimage")
        fake_skimage.morphology = fake_morph

        with patch.dict(sys.modules, {"skimage": fake_skimage, "skimage.morphology": fake_morph}):
            result = _skeletonize(mask)

        assert isinstance(result, np.ndarray)
        assert result.shape == mask.shape
        assert result.dtype == np.uint8
