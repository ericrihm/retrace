"""Error-state tests — verify graceful handling of failure scenarios.

Covers: network errors, invalid inputs, empty data states, I/O failures,
and corrupt/missing image paths across the main pipeline modules.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests as req

from retrace.core.pipeline import Pipeline
from retrace.detection.ocr import _crop_component, _run_ocr
from retrace.identification.matcher import _best_fuzzy_match, lookup_part
from retrace.sources.fcc import download_fcc_photos, search_fcc
from retrace.sources.ifixit import download_guide_images, search_ifixit


# ---------------------------------------------------------------------------
# sources/fcc.py — network and I/O error states
# ---------------------------------------------------------------------------

def test_search_fcc_http_error_returns_empty():
    """HTTP error from raise_for_status() returns empty list without crashing."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req.HTTPError("404 Not Found")

    with patch("retrace.sources.fcc.requests.get", return_value=mock_resp):
        results = search_fcc("anything")

    assert results == []


def test_search_fcc_empty_html_returns_empty():
    """Response HTML with no FCC-ID links returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<html><body><p>No results found.</p></body></html>"

    with patch("retrace.sources.fcc.requests.get", return_value=mock_resp):
        results = search_fcc("xyzzy unknown device 99999")

    assert results == []


def test_download_fcc_photos_network_error_returns_empty(tmp_path):
    """Network error fetching the FCC filing page returns empty list."""
    with patch(
        "retrace.sources.fcc.requests.get",
        side_effect=req.RequestException("connection timed out"),
    ):
        result = download_fcc_photos("TEST-001", tmp_path)

    assert result == []


def test_download_fcc_photos_no_photo_links_returns_empty(tmp_path):
    """Filing page with no internal-photo links returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<html><body><a href='/FCC-ID/X/user-manual'>User Manual</a></body></html>"

    with patch("retrace.sources.fcc.requests.get", return_value=mock_resp):
        result = download_fcc_photos("TEST-001", tmp_path)

    assert result == []


def test_download_fcc_photos_image_download_failure_is_skipped(tmp_path):
    """When individual image downloads fail, failed items are skipped silently."""
    filing_resp = MagicMock()
    filing_resp.raise_for_status = MagicMock()
    filing_resp.text = (
        "<html><body>"
        "<a href='/FCC-ID/TEST/internal-photo'>Internal Photos</a>"
        "</body></html>"
    )

    with patch(
        "retrace.sources.fcc.requests.get",
        side_effect=[filing_resp, req.RequestException("download failed")],
    ), patch("retrace.sources.fcc.time.sleep"):
        result = download_fcc_photos("TEST-001", tmp_path)

    assert result == []


def test_download_fcc_photos_oserror_on_write_skips_file(tmp_path):
    """OSError writing an image file is caught; the file is skipped, no crash."""
    filing_resp = MagicMock()
    filing_resp.raise_for_status = MagicMock()
    filing_resp.text = (
        "<html><body>"
        "<a href='/FCC-ID/TEST/internal'>Internal Photos</a>"
        "</body></html>"
    )
    img_resp = MagicMock()
    img_resp.raise_for_status = MagicMock()
    img_resp.headers = {"Content-Type": "image/jpeg"}
    img_resp.iter_content.return_value = [b"fakedata"]

    with patch(
        "retrace.sources.fcc.requests.get", side_effect=[filing_resp, img_resp]
    ), patch("retrace.sources.fcc.time.sleep"), patch.object(
        pathlib.Path, "open", side_effect=OSError("disk full")
    ):
        result = download_fcc_photos("TEST-001", tmp_path)

    assert isinstance(result, list)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# sources/ifixit.py — network and JSON error states
# ---------------------------------------------------------------------------

def test_search_ifixit_invalid_json_returns_empty():
    """ValueError from resp.json() is caught and returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1")

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        results = search_ifixit("any query")

    assert results == []


def test_search_ifixit_empty_results_list_returns_empty():
    """Response with an empty results list returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": []}

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        results = search_ifixit("totally obscure device xyz")

    assert results == []


def test_search_ifixit_non_guide_types_filtered_out():
    """Results with dataType other than guide/teardown are all filtered out."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"dataType": "article", "guideid": 1, "title": "A", "url": "", "image": {}, "category": "", "subject": ""},
            {"dataType": "wiki", "guideid": 2, "title": "B", "url": "", "image": {}, "category": "", "subject": ""},
        ]
    }

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        results = search_ifixit("something")

    assert results == []


def test_download_guide_images_network_error_returns_empty(tmp_path):
    """Network error fetching guide JSON returns empty list."""
    with patch(
        "retrace.sources.ifixit.requests.get",
        side_effect=req.RequestException("connection refused"),
    ):
        result = download_guide_images(12345, tmp_path)

    assert result == []


def test_download_guide_images_invalid_json_returns_empty(tmp_path):
    """ValueError from guide JSON endpoint returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("bad json")

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        result = download_guide_images(12345, tmp_path)

    assert result == []


def test_download_guide_images_no_steps_or_images_returns_empty(tmp_path):
    """Guide with empty steps and no primary image returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"steps": [], "image": None}

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        result = download_guide_images(12345, tmp_path)

    assert result == []


# ---------------------------------------------------------------------------
# core/pipeline.py — missing/unreadable image error states
# ---------------------------------------------------------------------------

def test_pipeline_load_image_raises_on_missing_file(tmp_path):
    """_load_image raises ValueError when cv2.imread returns None for a missing file."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("OpenCV not available")

    p = Pipeline()
    with pytest.raises(ValueError, match="Could not load image"):
        p._load_image(str(tmp_path / "nonexistent.jpg"))


def test_pipeline_run_raises_on_missing_file(tmp_path):
    """Pipeline.run() propagates ValueError when the image file does not exist."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("OpenCV not available")

    p = Pipeline()
    with pytest.raises(ValueError, match="Could not load image"):
        p.run(str(tmp_path / "nonexistent.jpg"))


# ---------------------------------------------------------------------------
# identification/matcher.py — invalid input states
# ---------------------------------------------------------------------------

def test_fuzzy_match_empty_string_returns_none():
    """Empty marking string returns None via early guard."""
    assert _best_fuzzy_match("") is None


def test_fuzzy_match_whitespace_only_returns_none():
    """Whitespace-only string strips to empty, scores 0 against all DB keys, returns None."""
    assert _best_fuzzy_match("   ") is None


def test_lookup_part_empty_string_returns_none():
    """Public lookup_part API returns None for empty input."""
    assert lookup_part("") is None


def test_fuzzy_match_completely_unrelated_string_returns_none():
    """A random unrelated string falls below the 0.55 threshold and returns None."""
    assert _best_fuzzy_match("XXXXXXXXXXX99999") is None


# ---------------------------------------------------------------------------
# detection/ocr.py — invalid crop and OCR failure states
# ---------------------------------------------------------------------------

def test_crop_component_zero_width_returns_none():
    """_crop_component returns None when bbox width is zero."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    assert _crop_component(img, (10, 10, 0, 20)) is None


def test_crop_component_zero_height_returns_none():
    """_crop_component returns None when bbox height is zero."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    assert _crop_component(img, (10, 10, 20, 0)) is None


def test_crop_component_bbox_outside_image_returns_none():
    """_crop_component returns None when bbox is fully outside image bounds."""
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    # x=60 on a 50-wide image: after clamping x2=50, x1=50 → x2 <= x1
    assert _crop_component(img, (60, 10, 20, 20)) is None


def test_run_ocr_readtext_exception_returns_empty_string():
    """_run_ocr returns empty string when reader.readtext raises an exception."""
    mock_reader = MagicMock()
    mock_reader.readtext.side_effect = RuntimeError("GPU out of memory")
    crop = np.zeros((20, 20, 3), dtype=np.uint8)

    result = _run_ocr(mock_reader, crop)

    assert result == ""


def test_run_ocr_low_confidence_results_filtered_out():
    """_run_ocr returns empty string when all detected text is below the 0.4 confidence threshold."""
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([0, 0, 10, 10], "JUNK", 0.1),
        ([0, 0, 10, 10], "NOISE", 0.35),
    ]
    crop = np.zeros((20, 20, 3), dtype=np.uint8)

    result = _run_ocr(mock_reader, crop)

    assert result == ""
