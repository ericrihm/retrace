"""Tests for retrace.sources.board_sourcer — all HTTP calls are mocked."""

from __future__ import annotations

from unittest.mock import patch

from retrace.sources.board_sourcer import download_all

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fcc(fcc_id: str) -> dict:
    return {"fcc_id": fcc_id, "description": f"Device {fcc_id}"}


def _ifixit(guideid: int, title: str = "Teardown") -> dict:
    return {"guideid": guideid, "title": title}


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_download_all_returns_total_count(tmp_path):
    """download_all() should return the sum of files from FCC + iFixit."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[tmp_path / "a.jpg", tmp_path / "b.jpg"]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[tmp_path / "c.jpg"]) as mock_ifixit:

        total = download_all(
            "router",
            fcc_results=[_fcc("AAAA-TEST1")],
            ifixit_results=[_ifixit(101)],
            dest_root=tmp_path,
        )

    assert total == 3
    mock_fcc.assert_called_once()
    mock_ifixit.assert_called_once()


def test_download_all_empty_results(tmp_path):
    """Empty result lists should return 0 downloads without calling adapters."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]) as mock_ifixit:

        total = download_all("nothing", fcc_results=[], ifixit_results=[], dest_root=tmp_path)

    assert total == 0
    mock_fcc.assert_not_called()
    mock_ifixit.assert_not_called()


def test_download_all_no_ifixit_results(tmp_path):
    """FCC-only scenario: iFixit adapter should not be called."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[tmp_path / "x.jpg"]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images") as mock_ifixit:

        total = download_all("cam", fcc_results=[_fcc("B1B1-CAM")], ifixit_results=[], dest_root=tmp_path)

    assert total == 1
    mock_fcc.assert_called_once()
    mock_ifixit.assert_not_called()


def test_download_all_no_fcc_results(tmp_path):
    """iFixit-only scenario: FCC adapter should not be called."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos") as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[tmp_path / "y.jpg"]) as mock_ifixit:

        total = download_all("phone", fcc_results=[], ifixit_results=[_ifixit(77)], dest_root=tmp_path)

    assert total == 1
    mock_fcc.assert_not_called()
    mock_ifixit.assert_called_once()


# ---------------------------------------------------------------------------
# Auto-search when results not pre-fetched
# ---------------------------------------------------------------------------

def test_download_all_calls_search_fcc_when_results_none(tmp_path):
    """When fcc_results=None, download_all() must call search_fcc(query)."""
    with patch("retrace.sources.board_sourcer.search_fcc", return_value=[]) as mock_search, \
         patch("retrace.sources.board_sourcer.download_fcc_photos") as mock_dl, \
         patch("retrace.sources.board_sourcer.search_ifixit", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_guide_images"):

        download_all("router", fcc_results=None, ifixit_results=[], dest_root=tmp_path)

    mock_search.assert_called_once_with("router")
    mock_dl.assert_not_called()


def test_download_all_calls_search_ifixit_when_results_none(tmp_path):
    """When ifixit_results=None, download_all() must call search_ifixit(query)."""
    with patch("retrace.sources.board_sourcer.search_fcc", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_fcc_photos"), \
         patch("retrace.sources.board_sourcer.search_ifixit", return_value=[]) as mock_search, \
         patch("retrace.sources.board_sourcer.download_guide_images"):

        download_all("camera", fcc_results=[], ifixit_results=None, dest_root=tmp_path)

    mock_search.assert_called_once_with("camera")


def test_download_all_both_sources_none_calls_both_searches(tmp_path):
    """When both result sets are None, both search functions must be called."""
    with patch("retrace.sources.board_sourcer.search_fcc", return_value=[]) as mock_fcc_s, \
         patch("retrace.sources.board_sourcer.download_fcc_photos"), \
         patch("retrace.sources.board_sourcer.search_ifixit", return_value=[]) as mock_ifixit_s, \
         patch("retrace.sources.board_sourcer.download_guide_images"):

        download_all("device", dest_root=tmp_path)

    mock_fcc_s.assert_called_once_with("device")
    mock_ifixit_s.assert_called_once_with("device")


# ---------------------------------------------------------------------------
# Directory routing
# ---------------------------------------------------------------------------

def test_download_all_passes_fcc_subdir(tmp_path):
    """FCC photos must be routed to <dest_root>/fcc/<fcc_id>/."""
    fcc_id = "ZZZZ-BOARD"

    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]):

        download_all("x", fcc_results=[_fcc(fcc_id)], ifixit_results=[], dest_root=tmp_path)

    called_dest = mock_fcc.call_args[0][1]
    assert str(called_dest).endswith(f"fcc/{fcc_id}")


def test_download_all_passes_ifixit_subdir(tmp_path):
    """iFixit images must be routed to <dest_root>/ifixit/<guideid>/."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]) as mock_ifixit:

        download_all("y", fcc_results=[], ifixit_results=[_ifixit(555)], dest_root=tmp_path)

    called_dest = mock_ifixit.call_args[0][1]
    assert str(called_dest).endswith("ifixit/555")


def test_download_all_dest_root_as_string(tmp_path):
    """dest_root can be supplied as a string (not just Path)."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]):

        # Should not raise
        total = download_all("z", fcc_results=[], ifixit_results=[], dest_root=str(tmp_path))

    assert total == 0


# ---------------------------------------------------------------------------
# max_fcc / max_ifixit limits
# ---------------------------------------------------------------------------

def test_download_all_respects_max_fcc(tmp_path):
    """Only the first max_fcc FCC filings should be downloaded."""
    filings = [_fcc(f"ID{i}") for i in range(10)]

    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]):

        download_all("board", fcc_results=filings, ifixit_results=[], dest_root=tmp_path, max_fcc=2)

    assert mock_fcc.call_count == 2
    called_ids = [c[0][0] for c in mock_fcc.call_args_list]
    assert called_ids == ["ID0", "ID1"]


def test_download_all_respects_max_ifixit(tmp_path):
    """Only the first max_ifixit guides should be downloaded."""
    guides = [_ifixit(i) for i in range(10)]

    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]) as mock_ifixit:

        download_all("phone", fcc_results=[], ifixit_results=guides, dest_root=tmp_path, max_ifixit=3)

    assert mock_ifixit.call_count == 3
    called_ids = [c[0][0] for c in mock_ifixit.call_args_list]
    assert called_ids == [0, 1, 2]


def test_download_all_skips_fcc_entry_without_fcc_id(tmp_path):
    """FCC entries missing 'fcc_id' must be silently skipped."""
    bad_filing = {"description": "no id here"}

    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]) as mock_fcc, \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]):

        total = download_all("x", fcc_results=[bad_filing], ifixit_results=[], dest_root=tmp_path)

    mock_fcc.assert_not_called()
    assert total == 0


def test_download_all_skips_ifixit_entry_without_guideid(tmp_path):
    """iFixit entries missing 'guideid' must be silently skipped."""
    bad_guide = {"title": "no id here"}

    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[]), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]) as mock_ifixit:

        total = download_all("y", fcc_results=[], ifixit_results=[bad_guide], dest_root=tmp_path)

    mock_ifixit.assert_not_called()
    assert total == 0


# ---------------------------------------------------------------------------
# Multi-file totals
# ---------------------------------------------------------------------------

def test_download_all_sums_across_multiple_filings(tmp_path):
    """Total should be the sum of all files across every downloaded filing."""
    file_batches = [[tmp_path / "a.jpg", tmp_path / "b.jpg"], [tmp_path / "c.jpg"]]

    with patch("retrace.sources.board_sourcer.download_fcc_photos", side_effect=file_batches), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[]):

        total = download_all(
            "multi",
            fcc_results=[_fcc("F1"), _fcc("F2")],
            ifixit_results=[],
            dest_root=tmp_path,
        )

    assert total == 3


def test_download_all_sums_fcc_and_ifixit(tmp_path):
    """Total should combine FCC and iFixit file counts."""
    with patch("retrace.sources.board_sourcer.download_fcc_photos", return_value=[tmp_path / "x.jpg"]), \
         patch("retrace.sources.board_sourcer.download_guide_images", return_value=[tmp_path / "y1.jpg", tmp_path / "y2.jpg"]):

        total = download_all(
            "combo",
            fcc_results=[_fcc("C1")],
            ifixit_results=[_ifixit(200)],
            dest_root=tmp_path,
        )

    assert total == 3
