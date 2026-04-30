"""Tests for retrace CLI — all heavy imports and network calls are mocked."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from retrace.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------

def test_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "PCB" in result.output or "retrace" in result.output.lower()


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_verbose_flag(runner):
    """--verbose should not crash the CLI before any subcommand."""
    result = runner.invoke(main, ["--verbose", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Subcommand --help
# ---------------------------------------------------------------------------

def test_scan_help(runner):
    result = runner.invoke(main, ["scan", "--help"])
    assert result.exit_code == 0
    assert "IMAGE" in result.output or "scan" in result.output.lower()


def test_search_help(runner):
    result = runner.invoke(main, ["search", "--help"])
    assert result.exit_code == 0
    assert "query" in result.output.lower() or "QUERY" in result.output


def test_trace_help(runner):
    result = runner.invoke(main, ["trace", "--help"])
    assert result.exit_code == 0


def test_advise_help(runner):
    result = runner.invoke(main, ["advise", "--help"])
    assert result.exit_code == 0


def test_ui_help(runner):
    result = runner.invoke(main, ["ui", "--help"])
    assert result.exit_code == 0


def test_report_help(runner):
    result = runner.invoke(main, ["report", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# scan — missing file gives an error
# ---------------------------------------------------------------------------

def test_scan_missing_file(runner):
    result = runner.invoke(main, ["scan", "/nonexistent/path/board.jpg"])
    # click.Path(exists=True) makes Click return exit_code 2 for missing files
    assert result.exit_code != 0
    assert "Error" in result.output or "Invalid" in result.output or result.exit_code == 2


def test_scan_missing_file_no_such_path(runner):
    result = runner.invoke(main, ["scan", "__definitely_does_not_exist__.png"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# search — network calls mocked
# ---------------------------------------------------------------------------

def test_search_command_basic(runner):
    """search should print results from both sources without hitting the network.

    The CLI imports search_fcc/search_ifixit inside the function body, so we
    patch at the source modules rather than at retrace.cli.
    """
    fcc_results = [{"fcc_id": "2ABCD-TEST1", "description": "Test widget"}]
    ifixit_results = [{"guideid": 99, "title": "Fix the board"}]

    with patch("retrace.sources.fcc.search_fcc", return_value=fcc_results), \
         patch("retrace.sources.ifixit.search_ifixit", return_value=ifixit_results):
        result = runner.invoke(main, ["search", "test board"])

    assert result.exit_code == 0
    assert "2ABCD-TEST1" in result.output
    assert "Fix the board" in result.output
    assert "Found 2 results" in result.output


def test_search_empty_results(runner):
    with patch("retrace.sources.fcc.search_fcc", return_value=[]), \
         patch("retrace.sources.ifixit.search_ifixit", return_value=[]):
        result = runner.invoke(main, ["search", "nothing here"])

    assert result.exit_code == 0
    assert "Found 0 results" in result.output


def test_search_limit_option(runner):
    fcc_results = [{"fcc_id": f"FCC{i}", "description": ""} for i in range(10)]
    ifixit_results = [{"guideid": i, "title": f"Guide {i}"} for i in range(10)]

    with patch("retrace.sources.fcc.search_fcc", return_value=fcc_results), \
         patch("retrace.sources.ifixit.search_ifixit", return_value=ifixit_results):
        result = runner.invoke(main, ["search", "widget", "--limit", "2"])

    assert result.exit_code == 0
    # Only 2 results per source should appear in output
    output_lines = result.output.splitlines()
    fcc_lines = [line for line in output_lines if "FCC" in line and ":" in line]
    ifixit_lines = [line for line in output_lines if "iFixit" in line]
    assert len(fcc_lines) <= 2
    assert len(ifixit_lines) <= 2


def test_search_with_download(runner, tmp_path):
    """--download should invoke board_sourcer.download_all."""
    fcc_results = [{"fcc_id": "XYZ-1"}]
    ifixit_results = [{"guideid": 42, "title": "Teardown"}]

    with patch("retrace.sources.fcc.search_fcc", return_value=fcc_results), \
         patch("retrace.sources.ifixit.search_ifixit", return_value=ifixit_results), \
         patch("retrace.sources.board_sourcer.download_all", return_value=3) as mock_dl:
        result = runner.invoke(main, ["search", "camera", "--download"])

    assert result.exit_code == 0
    assert "Downloaded 3 images" in result.output
    mock_dl.assert_called_once()
