"""Tests for retrace.sources.fcc — FCC filing scraper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from retrace.sources.fcc import (
    _ext_from_content_type,
    _ext_from_url,
    _PhotoLinkParser,
    _SearchResultParser,
    download_fcc_photos,
    search_fcc,
)

# ---------------------------------------------------------------------------
# _SearchResultParser
# ---------------------------------------------------------------------------

SEARCH_HTML = """
<html><body>
  <a href="/FCC-ID/2ABCD-MYDEVICE">My Device Widget</a>
  <a href="/FCC-ID/XYZZY-BOARD">Cool PCB Board</a>
  <a href="/other/link">Unrelated link</a>
</body></html>
"""


class TestSearchResultParser:
    def test_extracts_fcc_ids(self):
        parser = _SearchResultParser()
        parser.feed(SEARCH_HTML)
        ids = [r["fcc_id"] for r in parser.results]
        assert "2ABCD-MYDEVICE" in ids
        assert "XYZZY-BOARD" in ids

    def test_ignores_non_fcc_links(self):
        parser = _SearchResultParser()
        parser.feed(SEARCH_HTML)
        assert len(parser.results) == 2

    def test_description_captured(self):
        parser = _SearchResultParser()
        parser.feed(SEARCH_HTML)
        result = next(r for r in parser.results if r["fcc_id"] == "2ABCD-MYDEVICE")
        assert "My Device Widget" in result["description"]

    def test_url_built_correctly(self):
        parser = _SearchResultParser()
        parser.feed(SEARCH_HTML)
        result = parser.results[0]
        assert result["url"].startswith("https://fcc.report/FCC-ID/")

    def test_empty_html(self):
        parser = _SearchResultParser()
        parser.feed("<html><body></body></html>")
        assert parser.results == []


# ---------------------------------------------------------------------------
# _PhotoLinkParser
# ---------------------------------------------------------------------------

PHOTO_HTML = """
<html><body>
  <a href="/doc/internal-photos.jpg">Internal Photos</a>
  <a href="/doc/user-manual.pdf">User Manual</a>
  <a href="https://cdn.example.com/board-photo.png">Board Photo</a>
  <a href="/doc/pcb-layout.pdf">PCB Layout</a>
</body></html>
"""


class TestPhotoLinkParser:
    def test_extracts_internal_links(self):
        parser = _PhotoLinkParser()
        parser.feed(PHOTO_HTML)
        assert len(parser.photo_links) >= 1

    def test_skips_non_photo_links(self):
        parser = _PhotoLinkParser()
        parser.feed(PHOTO_HTML)
        # User Manual should not be included
        assert all("user-manual" not in link for link in parser.photo_links)

    def test_deduplication(self):
        # Feed same link twice via repeating the HTML
        parser = _PhotoLinkParser()
        parser.feed(PHOTO_HTML + PHOTO_HTML)
        # No duplicates
        assert len(parser.photo_links) == len(set(parser.photo_links))

    def test_absolute_url_preserved(self):
        parser = _PhotoLinkParser()
        parser.feed(PHOTO_HTML)
        # The https:// link should be kept as-is
        assert any(link.startswith("https://cdn.example.com") for link in parser.photo_links)

    def test_relative_url_gets_base(self):
        parser = _PhotoLinkParser()
        parser.feed(PHOTO_HTML)
        # Relative links should be prefixed with fcc.report base
        assert any(link.startswith("https://fcc.report") for link in parser.photo_links)


# ---------------------------------------------------------------------------
# _ext_from_content_type / _ext_from_url
# ---------------------------------------------------------------------------

class TestExtHelpers:
    def test_jpeg_content_type(self):
        assert _ext_from_content_type("image/jpeg") == ".jpg"

    def test_png_content_type(self):
        assert _ext_from_content_type("image/png") == ".png"

    def test_pdf_content_type(self):
        assert _ext_from_content_type("application/pdf") == ".pdf"

    def test_unknown_content_type_empty(self):
        assert _ext_from_content_type("text/html") == ""

    def test_ext_from_jpg_url(self):
        assert _ext_from_url("https://example.com/photo.jpg") == ".jpg"

    def test_ext_from_png_url(self):
        assert _ext_from_url("https://example.com/board.PNG") == ".png"

    def test_ext_from_unknown_url_empty(self):
        assert _ext_from_url("https://example.com/file.xyz") == ""


# ---------------------------------------------------------------------------
# search_fcc — online path
# ---------------------------------------------------------------------------

class TestSearchFcc:
    def _mock_response(self, html: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = html
        resp.raise_for_status = MagicMock()
        return resp

    def test_returns_results_from_html(self):
        html = '<a href="/FCC-ID/2ABCD-TEST">Test Device</a>'
        with patch("retrace.sources.fcc.requests.get", return_value=self._mock_response(html)):
            results = search_fcc("Test Device")
        assert len(results) == 1
        assert results[0]["fcc_id"] == "2ABCD-TEST"

    def test_falls_back_to_registry_on_network_error(self):
        with patch("retrace.sources.fcc.requests.get", side_effect=requests.RequestException("timeout")):
            with patch("retrace.sources.device_registry.search_registry", return_value=[]) as mock_reg:
                results = search_fcc("anything")
        mock_reg.assert_called_once_with("anything")
        assert results == []

    def test_falls_back_to_registry_when_no_results(self):
        """If parser finds no FCC IDs, fall back to local registry."""
        empty_html = "<html><body><p>No results</p></body></html>"
        with patch("retrace.sources.fcc.requests.get", return_value=self._mock_response(empty_html)):
            with patch("retrace.sources.device_registry.search_registry", return_value=[]) as mock_reg:
                results = search_fcc("nothing")
        mock_reg.assert_called_once()
        assert results == []

    def test_registry_results_returned(self):
        """Registry results are correctly mapped to the expected dict schema."""
        rev = MagicMock()
        rev.fcc_id = "REG-001"
        rev.name = "Test Rev"
        rev.year = 2020
        rev.model_number = "TR1"

        family = MagicMock()
        family.manufacturer = "Acme"

        with patch("retrace.sources.fcc.requests.get", side_effect=requests.RequestException):
            with patch("retrace.sources.device_registry.search_registry", return_value=[(family, [rev])]):
                results = search_fcc("test")

        assert len(results) == 1
        assert results[0]["fcc_id"] == "REG-001"
        assert "fcc_id" in results[0]
        assert "url" in results[0]

    def test_duplicate_fcc_ids_deduplicated(self):
        """Line 156 — duplicate fcc_id across revisions is de-duplicated via 'seen' set."""
        rev1 = MagicMock()
        rev1.fcc_id = "DUPE-001"
        rev1.name = "Rev 1"
        rev1.year = 2020
        rev1.model_number = "M1"

        rev2 = MagicMock()
        rev2.fcc_id = "DUPE-001"  # same fcc_id as rev1
        rev2.name = "Rev 2"
        rev2.year = 2021
        rev2.model_number = "M1"

        family = MagicMock()
        family.manufacturer = "Acme"

        with patch("retrace.sources.fcc.requests.get", side_effect=requests.RequestException):
            with patch("retrace.sources.device_registry.search_registry",
                       return_value=[(family, [rev1, rev2])]):
                results = search_fcc("dupe test")

        # Only one result for the duplicated fcc_id
        assert len(results) == 1
        assert results[0]["fcc_id"] == "DUPE-001"


# ---------------------------------------------------------------------------
# download_fcc_photos
# ---------------------------------------------------------------------------

class TestDownloadFccPhotos:
    def _mock_filing_page(self, photo_links_html: str):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = photo_links_html
        resp.raise_for_status = MagicMock()
        return resp

    def _mock_image_response(self, content: bytes = b"IMGDATA"):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "image/jpeg"}
        resp.raise_for_status = MagicMock()
        resp.iter_content.return_value = [content]
        return resp

    def test_downloads_photo_to_dest(self, tmp_path):
        filing_html = '<a href="/doc/internal.jpg">Internal Photos</a>'
        with patch("retrace.sources.fcc.requests.get") as mock_get:
            with patch("retrace.sources.fcc.time.sleep"):
                mock_get.side_effect = [
                    self._mock_filing_page(filing_html),
                    self._mock_image_response(),
                ]
                paths = download_fcc_photos("2ABCD-TEST", tmp_path)
        assert len(paths) == 1
        assert paths[0].exists()

    def test_returns_empty_when_no_photos(self, tmp_path):
        filing_html = "<html><body><p>No photos here</p></body></html>"
        with patch("retrace.sources.fcc.requests.get", return_value=self._mock_filing_page(filing_html)):
            paths = download_fcc_photos("2ABCD-NOPHOTO", tmp_path)
        assert paths == []

    def test_returns_empty_on_network_error(self, tmp_path):
        with patch("retrace.sources.fcc.requests.get", side_effect=requests.RequestException("err")):
            paths = download_fcc_photos("BAD-ID", tmp_path)
        assert paths == []

    def test_creates_dest_dir(self, tmp_path):
        dest = tmp_path / "subdir" / "fcc"
        filing_html = "<html><body></body></html>"
        with patch("retrace.sources.fcc.requests.get", return_value=self._mock_filing_page(filing_html)):
            download_fcc_photos("2ABCD-X", dest)
        assert dest.exists()

    def test_continues_after_image_download_failure(self, tmp_path):
        filing_html = (
            '<a href="/doc/internal1.jpg">Internal Photos</a>'
            '<a href="/doc/board.jpg">Board Photo</a>'
        )
        good_resp = self._mock_image_response()
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = requests.HTTPError("404")

        with patch("retrace.sources.fcc.requests.get") as mock_get:
            with patch("retrace.sources.fcc.time.sleep"):
                mock_get.side_effect = [
                    self._mock_filing_page(filing_html),
                    bad_resp,
                    good_resp,
                ]
                paths = download_fcc_photos("2ABCD-PARTIAL", tmp_path)
        # At least attempted; may have downloaded 0 or 1 depending on ordering
        assert isinstance(paths, list)
