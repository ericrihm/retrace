"""Tests for FCC and iFixit source adapters — all HTTP mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from retrace.sources.fcc import (
    _ext_from_content_type,
    _ext_from_url,
    _SearchResultParser,
    search_fcc,
)
from retrace.sources.ifixit import search_ifixit


# ---------------------------------------------------------------------------
# FCC helper tests
# ---------------------------------------------------------------------------

def test_ext_from_content_type_jpeg():
    assert _ext_from_content_type("image/jpeg") == ".jpg"


def test_ext_from_content_type_png():
    assert _ext_from_content_type("image/png") == ".png"


def test_ext_from_content_type_pdf():
    assert _ext_from_content_type("application/pdf") == ".pdf"


def test_ext_from_content_type_unknown():
    assert _ext_from_content_type("text/html") == ""


def test_ext_from_url_jpg():
    assert _ext_from_url("https://example.com/board.jpg") == ".jpg"


def test_ext_from_url_no_extension():
    assert _ext_from_url("https://example.com/path/noext") == ""


# ---------------------------------------------------------------------------
# FCC HTML parser tests
# ---------------------------------------------------------------------------

def test_search_result_parser_extracts_fcc_id():
    html = """
    <html><body>
    <a href="/FCC-ID/2ABCD-MYDEVICE">My Device — Acme Corp</a>
    <a href="/FCC-ID/XYZW1234">Another Device</a>
    </body></html>
    """
    parser = _SearchResultParser()
    parser.feed(html)
    ids = [r["fcc_id"] for r in parser.results]
    assert "2ABCD-MYDEVICE" in ids
    assert "XYZW1234" in ids


# ---------------------------------------------------------------------------
# search_fcc() with mocked HTTP
# ---------------------------------------------------------------------------

def test_search_fcc_returns_results():
    mock_html = """
    <html><body>
    <a href="/FCC-ID/TEST-001">Test Device Alpha</a>
    <a href="/FCC-ID/TEST-002">Test Device Beta</a>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = mock_html

    with patch("retrace.sources.fcc.requests.get", return_value=mock_resp):
        results = search_fcc("test device")

    assert len(results) == 2
    fcc_ids = [r["fcc_id"] for r in results]
    assert "TEST-001" in fcc_ids


def test_search_fcc_returns_empty_on_network_error():
    import requests as req

    with patch("retrace.sources.fcc.requests.get", side_effect=req.RequestException("timeout")):
        results = search_fcc("anything")

    assert results == []


# ---------------------------------------------------------------------------
# search_ifixit() with mocked HTTP
# ---------------------------------------------------------------------------

def test_search_ifixit_returns_guides():
    mock_json = {
        "results": [
            {
                "dataType": "teardown",
                "guideid": 99999,
                "title": "Neptune Apex Teardown",
                "url": "https://www.ifixit.com/Teardown/Neptune+Apex/99999",
                "image": {"text": "https://guide-images.cdn.ifixit.com/igi/fake.jpg"},
                "category": "Aquarium Controllers",
                "subject": "Neptune Apex",
            },
            {
                "dataType": "article",  # should be skipped
                "guideid": 88888,
                "title": "Some Article",
                "url": "https://www.ifixit.com/Article/foo",
                "image": {},
                "category": "Misc",
                "subject": "Misc",
            },
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = mock_json

    with patch("retrace.sources.ifixit.requests.get", return_value=mock_resp):
        results = search_ifixit("Neptune Apex")

    assert len(results) == 1
    assert results[0]["guideid"] == 99999
    assert results[0]["type"] == "teardown"


def test_search_ifixit_returns_empty_on_network_error():
    import requests as req

    with patch("retrace.sources.ifixit.requests.get", side_effect=req.RequestException("timeout")):
        results = search_ifixit("anything")

    assert results == []
