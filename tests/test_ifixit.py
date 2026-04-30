"""Tests for retrace.sources.ifixit — iFixit API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from retrace.sources.ifixit import (
    _ext_from_url,
    download_guide_images,
    search_ifixit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_response(hits: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"results": hits}
    resp.raise_for_status = MagicMock()
    return resp


def _make_guide_response(steps: list[dict], primary_image: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "steps": steps,
        "image": {"original": primary_image} if primary_image else None,
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_image_response(content: bytes = b"IMGDATA") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.iter_content.return_value = [content]
    return resp


# ---------------------------------------------------------------------------
# _ext_from_url
# ---------------------------------------------------------------------------

class TestExtFromUrl:
    def test_jpg(self):
        assert _ext_from_url("https://ifixit.com/image.jpg") == ".jpg"

    def test_jpeg(self):
        assert _ext_from_url("https://ifixit.com/image.jpeg") == ".jpeg"

    def test_png(self):
        assert _ext_from_url("https://ifixit.com/image.PNG") == ".png"

    def test_unknown_extension(self):
        assert _ext_from_url("https://ifixit.com/image.tiff") == ""

    def test_no_extension(self):
        assert _ext_from_url("https://ifixit.com/image") == ""


# ---------------------------------------------------------------------------
# search_ifixit
# ---------------------------------------------------------------------------

class TestSearchIfixit:
    def test_returns_guides_only(self):
        hits = [
            {
                "dataType": "guide",
                "guideid": 1000,
                "title": "Neptune Apex Teardown",
                "url": "https://ifixit.com/guide/1000",
                "image": {"text": "https://img.example.com/thumb.jpg"},
                "category": "Electronics",
                "subject": "Neptune Apex",
            },
            {
                "dataType": "answer",  # should be filtered out
                "guideid": None,
                "title": "Q&A answer",
                "url": "",
                "image": {},
                "category": "",
                "subject": "",
            },
        ]
        with patch("retrace.sources.ifixit.requests.get", return_value=_make_search_response(hits)):
            results = search_ifixit("Neptune Apex")

        assert len(results) == 1
        assert results[0]["guideid"] == 1000
        assert results[0]["type"] == "guide"

    def test_teardown_type_included(self):
        hits = [
            {
                "dataType": "teardown",
                "guideid": 2000,
                "title": "Widget Teardown",
                "url": "",
                "image": {},
                "category": "",
                "subject": "",
            }
        ]
        with patch("retrace.sources.ifixit.requests.get", return_value=_make_search_response(hits)):
            results = search_ifixit("Widget")
        assert len(results) == 1
        assert results[0]["type"] == "teardown"

    def test_empty_results(self):
        with patch("retrace.sources.ifixit.requests.get", return_value=_make_search_response([])):
            results = search_ifixit("nonexistent")
        assert results == []

    def test_network_error_returns_empty(self):
        with patch("retrace.sources.ifixit.requests.get", side_effect=requests.RequestException("timeout")):
            results = search_ifixit("anything")
        assert results == []

    def test_invalid_json_returns_empty(self):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("bad json")
        with patch("retrace.sources.ifixit.requests.get", return_value=resp):
            results = search_ifixit("test")
        assert results == []

    def test_result_schema(self):
        hits = [
            {
                "dataType": "guide",
                "guideid": 3000,
                "title": "My Guide",
                "url": "https://ifixit.com/guide/3000",
                "image": {"text": "https://img.example.com/t.jpg"},
                "category": "Electronics",
                "subject": "My Device",
            }
        ]
        with patch("retrace.sources.ifixit.requests.get", return_value=_make_search_response(hits)):
            results = search_ifixit("My Device")
        r = results[0]
        for key in ("guideid", "title", "url", "image_url", "category", "subject", "type"):
            assert key in r


# ---------------------------------------------------------------------------
# download_guide_images
# ---------------------------------------------------------------------------

class TestDownloadGuideImages:
    def test_downloads_step_images(self, tmp_path):
        steps = [
            {
                "media": {
                    "data": [{"original": "https://img.example.com/step1.jpg"}]
                }
            }
        ]
        guide_resp = _make_guide_response(steps)
        img_resp = _make_image_response()

        with patch("retrace.sources.ifixit.requests.get") as mock_get:
            with patch("retrace.sources.ifixit.time.sleep"):
                mock_get.side_effect = [guide_resp, img_resp]
                paths = download_guide_images(125000, tmp_path)

        assert len(paths) == 1
        assert paths[0].exists()

    def test_includes_primary_image(self, tmp_path):
        guide_resp = _make_guide_response(steps=[], primary_image="https://img.example.com/primary.jpg")
        img_resp = _make_image_response()

        with patch("retrace.sources.ifixit.requests.get") as mock_get:
            with patch("retrace.sources.ifixit.time.sleep"):
                mock_get.side_effect = [guide_resp, img_resp]
                paths = download_guide_images(9999, tmp_path)

        assert len(paths) == 1

    def test_returns_empty_when_no_images(self, tmp_path):
        guide_resp = _make_guide_response(steps=[])
        with patch("retrace.sources.ifixit.requests.get", return_value=guide_resp):
            paths = download_guide_images(0, tmp_path)
        assert paths == []

    def test_network_error_returns_empty(self, tmp_path):
        with patch("retrace.sources.ifixit.requests.get", side_effect=requests.RequestException("err")):
            paths = download_guide_images(1, tmp_path)
        assert paths == []

    def test_invalid_json_returns_empty(self, tmp_path):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("bad json")
        with patch("retrace.sources.ifixit.requests.get", return_value=resp):
            paths = download_guide_images(1, tmp_path)
        assert paths == []

    def test_creates_dest_dir(self, tmp_path):
        dest = tmp_path / "nested" / "ifixit"
        guide_resp = _make_guide_response(steps=[])
        with patch("retrace.sources.ifixit.requests.get", return_value=guide_resp):
            download_guide_images(1, dest)
        assert dest.exists()

    def test_prefers_original_over_lower_res(self, tmp_path):
        """When a step has original + medium, only original should be collected."""
        steps = [
            {
                "media": {
                    "data": [
                        {
                            "original": "https://img.example.com/orig.jpg",
                            "medium": "https://img.example.com/med.jpg",
                        }
                    ]
                }
            }
        ]
        guide_resp = _make_guide_response(steps)
        img_resp = _make_image_response()

        with patch("retrace.sources.ifixit.requests.get") as mock_get:
            with patch("retrace.sources.ifixit.time.sleep"):
                mock_get.side_effect = [guide_resp, img_resp]
                paths = download_guide_images(42, tmp_path)

        assert len(paths) == 1  # only one URL fetched

    def test_image_download_failure_skipped(self, tmp_path):
        steps = [
            {"media": {"data": [{"original": "https://img.example.com/bad.jpg"}]}}
        ]
        guide_resp = _make_guide_response(steps)
        bad_img = MagicMock()
        bad_img.raise_for_status.side_effect = requests.HTTPError("404")

        with patch("retrace.sources.ifixit.requests.get") as mock_get:
            with patch("retrace.sources.ifixit.time.sleep"):
                mock_get.side_effect = [guide_resp, bad_img]
                paths = download_guide_images(7, tmp_path)

        assert paths == []
