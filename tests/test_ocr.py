"""Tests for retrace.detection.ocr — chip marking OCR."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from retrace.core.pipeline import Component
from retrace.detection import ocr as ocr_mod
from retrace.detection.ocr import (
    _crop_component,
    _run_ocr,
    read_markings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_component(label: str = "ic", bbox: tuple = (10, 10, 50, 30)) -> Component:
    return Component(
        id="c1",
        label=label,
        confidence=0.9,
        bbox=bbox,
    )


def _blank_image(h: int = 100, w: int = 100) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# _crop_component
# ---------------------------------------------------------------------------

class TestCropComponent:
    def test_normal_crop(self):
        img = _blank_image(100, 100)
        crop = _crop_component(img, (10, 10, 40, 30))
        assert crop is not None
        assert crop.shape[0] > 0 and crop.shape[1] > 0

    def test_zero_width_returns_none(self):
        img = _blank_image(100, 100)
        assert _crop_component(img, (10, 10, 0, 30)) is None

    def test_zero_height_returns_none(self):
        img = _blank_image(100, 100)
        assert _crop_component(img, (10, 10, 40, 0)) is None

    def test_out_of_bounds_returns_none(self):
        img = _blank_image(100, 100)
        # x,y far outside image
        result = _crop_component(img, (200, 200, 50, 50))
        assert result is None

    def test_partial_out_of_bounds_clamped(self):
        img = _blank_image(100, 100)
        # bbox extends beyond right/bottom edge — should still return a crop
        crop = _crop_component(img, (80, 80, 50, 50))
        assert crop is not None

    def test_padding_added(self):
        img = _blank_image(200, 200)
        # crop without padding would be 40×30; with 5% min-pad it grows slightly
        crop_base = _crop_component(img, (50, 50, 40, 30))
        assert crop_base is not None


# ---------------------------------------------------------------------------
# _run_ocr
# ---------------------------------------------------------------------------

class TestRunOcr:
    def _make_reader(self, results):
        reader = MagicMock()
        reader.readtext.return_value = results
        return reader

    def test_returns_text_above_threshold(self):
        reader = self._make_reader([[None, "STM32", 0.95]])
        crop = _blank_image(20, 60)
        assert _run_ocr(reader, crop) == "STM32"

    def test_filters_low_confidence(self):
        reader = self._make_reader([[None, "noise", 0.2]])
        crop = _blank_image(20, 60)
        assert _run_ocr(reader, crop) == ""

    def test_joins_multiple_tokens(self):
        reader = self._make_reader([
            [None, "STM32", 0.9],
            [None, "F103", 0.85],
        ])
        crop = _blank_image(20, 60)
        result = _run_ocr(reader, crop)
        assert "STM32" in result and "F103" in result

    def test_empty_results(self):
        reader = self._make_reader([])
        assert _run_ocr(reader, _blank_image()) == ""

    def test_handles_readtext_exception(self):
        reader = MagicMock()
        reader.readtext.side_effect = RuntimeError("GPU error")
        assert _run_ocr(reader, _blank_image()) == ""


# ---------------------------------------------------------------------------
# read_markings (public API)
# ---------------------------------------------------------------------------

class TestReadMarkings:
    def test_returns_unchanged_when_easyocr_missing(self):
        """When easyocr is unavailable, components are returned as-is."""
        comps = [_make_component("ic")]
        img = _blank_image()
        with patch.object(ocr_mod, "_get_reader", return_value=None):
            result = read_markings(img, comps)
        assert result == comps

    def test_non_ocr_labels_passed_through(self):
        """Components with non-OCR labels (e.g. capacitor) are not processed."""
        comps = [_make_component("capacitor")]
        img = _blank_image()
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [[None, "JUNK", 0.99]]
        with patch.object(ocr_mod, "_get_reader", return_value=mock_reader):
            result = read_markings(img, comps)
        # readtext should NOT have been called for a capacitor
        mock_reader.readtext.assert_not_called()
        assert result[0].marking == ""

    def test_marking_populated_for_ic(self):
        """IC components get their marking field updated from OCR."""
        comp = _make_component("ic", bbox=(5, 5, 60, 40))
        img = _blank_image(200, 200)
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [[None, "NE555", 0.9]]
        with patch.object(ocr_mod, "_get_reader", return_value=mock_reader):
            result = read_markings(img, [comp])
        assert result[0].marking == "NE555"

    def test_empty_component_list(self):
        img = _blank_image()
        with patch.object(ocr_mod, "_get_reader", return_value=MagicMock()):
            result = read_markings(img, [])
        assert result == []

    def test_tiny_crop_skipped(self):
        """Components with a crop area < _MIN_CROP_AREA are skipped."""
        comp = _make_component("ic", bbox=(0, 0, 2, 2))  # 4 px² < 64 px²
        img = _blank_image()
        mock_reader = MagicMock()
        with patch.object(ocr_mod, "_get_reader", return_value=mock_reader):
            result = read_markings(img, [comp])
        mock_reader.readtext.assert_not_called()
        assert result[0].marking == ""

    def test_default_languages_en(self):
        """Default languages list is ['en']."""
        img = _blank_image()
        with patch.object(ocr_mod, "_get_reader", return_value=None) as mock_get:
            read_markings(img, [])
        mock_get.assert_called_once_with(languages=["en"], gpu=False)


# ---------------------------------------------------------------------------
# _get_reader — import-error path
# ---------------------------------------------------------------------------

class TestGetReader:
    def test_returns_none_when_easyocr_not_installed(self):
        # Clear cache so the import attempt runs
        ocr_mod._reader_cache.clear()
        with patch.dict("sys.modules", {"easyocr": None}):
            reader = ocr_mod._get_reader(languages=["en"], gpu=False)
        assert reader is None

    def test_caches_reader(self):
        ocr_mod._reader_cache.clear()
        fake_reader = MagicMock()
        fake_easyocr = MagicMock()
        fake_easyocr.Reader.return_value = fake_reader
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            r1 = ocr_mod._get_reader(languages=["en"], gpu=False)
            r2 = ocr_mod._get_reader(languages=["en"], gpu=False)
        assert r1 is r2
        assert fake_easyocr.Reader.call_count == 1
        ocr_mod._reader_cache.clear()
