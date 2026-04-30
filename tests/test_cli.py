"""Tests for retrace CLI — all heavy imports and network calls are mocked."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# --quiet flag
# ---------------------------------------------------------------------------

def test_quiet_flag(runner):
    result = runner.invoke(main, ["--quiet", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# compare command
# ---------------------------------------------------------------------------

def test_compare_help(runner):
    result = runner.invoke(main, ["compare", "--help"])
    assert result.exit_code == 0
    assert "IMAGE_A" in result.output or "compare" in result.output.lower()


def test_compare_missing_file(runner):
    result = runner.invoke(main, ["compare", "/no/such/file.jpg", "/also/no.jpg"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# identify command
# ---------------------------------------------------------------------------

def test_identify_help(runner):
    result = runner.invoke(main, ["identify", "--help"])
    assert result.exit_code == 0
    assert "MARKING" in result.output


def test_identify_found(runner):
    match = {
        "part": "STM32F030C8T6",
        "manufacturer": "STMicroelectronics",
        "description": "ARM Cortex-M0",
        "package": "LQFP48",
        "category": "mcu",
        "datasheet": "https://example.com/ds.pdf",
    }
    with patch("retrace.identification.matcher.lookup_part", return_value=match):
        result = runner.invoke(main, ["identify", "STM32F030"])
    assert result.exit_code == 0
    assert "STM32F030C8T6" in result.output
    assert "STMicroelectronics" in result.output


def test_identify_not_found(runner):
    with patch("retrace.identification.matcher.lookup_part", return_value=None):
        result = runner.invoke(main, ["identify", "XYZNOPART"])
    assert result.exit_code != 0


def test_identify_json_output(runner):
    match = {"part": "LM7805", "manufacturer": "TI", "description": "5V regulator"}
    with patch("retrace.identification.matcher.lookup_part", return_value=match):
        result = runner.invoke(main, ["identify", "LM7805", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["part"] == "LM7805"


# ---------------------------------------------------------------------------
# search --json
# ---------------------------------------------------------------------------

def test_search_json_output(runner):
    fcc_results = [{"fcc_id": "ABC-123", "description": "Widget"}]
    ifixit_results = [{"guideid": 1, "title": "Teardown"}]
    with patch("retrace.sources.fcc.search_fcc", return_value=fcc_results), \
         patch("retrace.sources.ifixit.search_ifixit", return_value=ifixit_results):
        result = runner.invoke(main, ["search", "test", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["query"] == "test"
    assert len(data["fcc"]) == 1


# ---------------------------------------------------------------------------
# report --json
# ---------------------------------------------------------------------------

def test_report_json_output(runner):
    with patch("retrace.learning.engine.generate_report", return_value="report text"):
        result = runner.invoke(main, ["report", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "report" in data


# ---------------------------------------------------------------------------
# new commands help
# ---------------------------------------------------------------------------

def test_debug_help(runner):
    result = runner.invoke(main, ["debug", "--help"])
    assert result.exit_code == 0


def test_learn_help(runner):
    result = runner.invoke(main, ["learn", "--help"])
    assert result.exit_code == 0


def test_cross_board_help(runner):
    result = runner.invoke(main, ["cross-board", "--help"])
    assert result.exit_code == 0


def test_export_help(runner):
    result = runner.invoke(main, ["export", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# trace — functional test with mocked extractor
# ---------------------------------------------------------------------------

def test_trace_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    save_mock = lambda path: None
    trace_result = {
        "trace_count": 12,
        "junction_count": 3,
        "save": save_mock,
    }
    with patch("retrace.detection.trace_extractor.extract_traces", return_value=trace_result):
        result = runner.invoke(main, ["trace", str(img)])
    assert result.exit_code == 0
    assert "12 traces" in result.output
    assert "3 junctions" in result.output


# ---------------------------------------------------------------------------
# advise — functional test with mocked advisor
# ---------------------------------------------------------------------------

def _make_analysis_result(image_path="board.png", components=None, traces=None):
    """Helper to build a minimal AnalysisResult for CLI tests."""
    from retrace.core.pipeline import AnalysisResult, Component, Trace
    return AnalysisResult(
        image_path=image_path,
        components=components or [
            Component(id="U1", label="ic", confidence=0.95, bbox=(10, 10, 50, 50),
                      marking="STM32", part_number="STM32F030"),
            Component(id="R1", label="resistor", confidence=0.90, bbox=(70, 10, 20, 10)),
        ],
        traces=traces or [
            Trace(id="T1", points=[(30, 30), (80, 15)], from_component="U1", to_component="R1"),
        ],
        board_dimensions=(800, 600),
    )


def test_advise_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    recs = [
        {"location": (100, 200), "reason": "High entropy node", "entropy_reduction": 1.5},
        {"location": (300, 400), "reason": "Unresolved net", "entropy_reduction": 0.8},
    ]
    with patch("retrace.analysis.probe_advisor.ProbeAdvisor.recommend", return_value=recs):
        result = runner.invoke(main, ["advise", str(img)])
    assert result.exit_code == 0
    assert "probe" in result.output.lower() or "information gain" in result.output.lower()


def test_advise_json(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    recs = [
        {"location": (100, 200), "reason": "High entropy node", "entropy_reduction": 1.5},
    ]
    with patch("retrace.analysis.probe_advisor.ProbeAdvisor.recommend", return_value=recs):
        result = runner.invoke(main, ["advise", str(img), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["entropy_reduction"] == 1.5


# ---------------------------------------------------------------------------
# debug — functional test with mocked pipeline and analyzer
# ---------------------------------------------------------------------------

def test_debug_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    debug_output = {
        "summary": "Found 2 debug interfaces",
        "findings": [
            {
                "severity": "high",
                "interface": "JTAG",
                "description": "Exposed JTAG header",
                "component_label": "J5",
                "component_marking": "ARM-JTAG-20",
                "cve_reference": "CWE-1191",
            },
            {
                "severity": "medium",
                "interface": "UART",
                "description": "Serial console",
                "component_label": "J10",
                "component_marking": "UART-HDR",
                "cve_reference": "",
            },
        ],
    }
    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.plugins.builtin.debug_interfaces.DebugInterfaceAnalyzer.analyze",
               return_value=debug_output):
        result = runner.invoke(main, ["debug", str(img)])
    assert result.exit_code == 0
    assert "JTAG" in result.output
    assert "UART" in result.output
    assert "[HIGH]" in result.output
    assert "[MEDIUM]" in result.output


def test_debug_json(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    debug_output = {
        "summary": "No debug interfaces",
        "findings": [],
    }
    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.plugins.builtin.debug_interfaces.DebugInterfaceAnalyzer.analyze",
               return_value=debug_output):
        result = runner.invoke(main, ["debug", str(img), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["findings"] == []


def test_debug_no_findings(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    debug_output = {
        "summary": "No debug interfaces detected",
        "findings": [],
    }
    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.plugins.builtin.debug_interfaces.DebugInterfaceAnalyzer.analyze",
               return_value=debug_output):
        result = runner.invoke(main, ["debug", str(img)])
    assert result.exit_code == 0
    assert "No debug interfaces" in result.output


# ---------------------------------------------------------------------------
# learn — functional test with mocked learn_component
# ---------------------------------------------------------------------------

def test_learn_command(runner):
    with patch("retrace.identification.matcher.learn_component") as mock_learn:
        result = runner.invoke(main, [
            "learn", "ATmega328P",
            "--manufacturer", "Microchip",
            "--package", "TQFP-32",
            "--category", "mcu",
            "--aliases", "ATMEGA328P-AU,ATMEGA328P-PU",
            "--description", "8-bit AVR microcontroller",
        ])
    assert result.exit_code == 0
    assert "Learned: ATmega328P" in result.output
    assert "Microchip" in result.output
    assert "TQFP-32" in result.output
    mock_learn.assert_called_once()
    entry = mock_learn.call_args[0][0]
    assert entry["part"] == "ATmega328P"
    assert "ATMEGA328P-AU" in entry["aliases"]


def test_learn_minimal(runner):
    with patch("retrace.identification.matcher.learn_component"):
        result = runner.invoke(main, ["learn", "LM317"])
    assert result.exit_code == 0
    assert "Learned: LM317" in result.output


def test_learn_error(runner):
    with patch("retrace.identification.matcher.learn_component", side_effect=ValueError("duplicate")):
        result = runner.invoke(main, ["learn", "BAD_PART"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# cross-board — functional test with mocked pipeline and engine
# ---------------------------------------------------------------------------

def test_cross_board_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    from retrace.analysis.cross_board import BoardAnalysis, PatternMatch
    analysis = BoardAnalysis(
        matches=[
            PatternMatch(
                pattern_name="voltage_regulator",
                score=0.85,
                is_partial=False,
                description="Linear voltage regulator circuit",
                component_roles={"regulator": "U1", "input_cap": "C1", "output_cap": "C2"},
            ),
        ],
        novel_components=["R1"],
        coverage=0.67,
    )

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.analysis.cross_board.CrossBoardEngine.analyse", return_value=analysis):
        result = runner.invoke(main, ["cross-board", str(img)])
    assert result.exit_code == 0
    assert "voltage_regulator" in result.output
    assert "0.85" in result.output
    assert "R1" in result.output


def test_cross_board_json(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    from retrace.analysis.cross_board import BoardAnalysis, PatternMatch
    analysis = BoardAnalysis(
        matches=[
            PatternMatch(
                pattern_name="decoupling",
                score=0.72,
                is_partial=True,
                description="Decoupling capacitor pair",
                component_roles={"cap": "C1"},
            ),
        ],
        novel_components=[],
        coverage=0.50,
    )

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.analysis.cross_board.CrossBoardEngine.analyse", return_value=analysis):
        result = runner.invoke(main, ["cross-board", str(img), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["matches"][0]["pattern"] == "decoupling"
    assert data["matches"][0]["partial"] is True
    assert data["coverage"] == 0.50


def test_cross_board_no_matches(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    from retrace.analysis.cross_board import BoardAnalysis
    analysis = BoardAnalysis(matches=[], novel_components=["U1", "R1"], coverage=0.0)

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.analysis.cross_board.CrossBoardEngine.analyse", return_value=analysis):
        result = runner.invoke(main, ["cross-board", str(img)])
    assert result.exit_code == 0
    assert "No known subcircuit patterns" in result.output


# ---------------------------------------------------------------------------
# export — functional test with mocked pipeline
# ---------------------------------------------------------------------------

def test_export_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    out_dir = tmp_path / "export_out"

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["export", str(img), "-o", str(out_dir)])
    assert result.exit_code == 0
    assert "Exported" in result.output
    assert "2 component(s)" in result.output


def test_export_csv_format(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    out_dir = tmp_path / "csv_out"

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["export", str(img), "--format", "csv", "-o", str(out_dir)])
    assert result.exit_code == 0
    assert "[csv]" in result.output


# ---------------------------------------------------------------------------
# compare — success path with mocked pipeline
# ---------------------------------------------------------------------------

def test_compare_identical_boards(runner, tmp_path):
    img_a = tmp_path / "board_v1.png"
    img_b = tmp_path / "board_v2.png"
    img_a.write_bytes(b"\x89PNG\r\n\x1a\n")
    img_b.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result()

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["compare", str(img_a), str(img_b)])
    assert result.exit_code == 0
    assert "No differences" in result.output


def test_compare_different_boards(runner, tmp_path):
    from retrace.core.pipeline import AnalysisResult, Component, Trace
    img_a = tmp_path / "board_v1.png"
    img_b = tmp_path / "board_v2.png"
    img_a.write_bytes(b"\x89PNG\r\n\x1a\n")
    img_b.write_bytes(b"\x89PNG\r\n\x1a\n")

    result_a = AnalysisResult(
        image_path=str(img_a),
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(10, 10, 50, 50), marking="OLD"),
            Component(id="R1", label="resistor", confidence=0.9, bbox=(70, 10, 20, 10)),
        ],
        traces=[],
    )
    result_b = AnalysisResult(
        image_path=str(img_b),
        components=[
            Component(id="U1", label="ic", confidence=0.9, bbox=(10, 10, 50, 50), marking="NEW"),
            Component(id="C1", label="capacitor", confidence=0.85, bbox=(100, 100, 15, 15)),
        ],
        traces=[],
    )

    with patch("retrace.core.pipeline.Pipeline.run", side_effect=[result_a, result_b]):
        result = runner.invoke(main, ["compare", str(img_a), str(img_b)])
    assert result.exit_code == 0
    assert "Added" in result.output
    assert "C1" in result.output
    assert "Removed" in result.output
    assert "R1" in result.output
    assert "Changed" in result.output
    assert "OLD" in result.output
    assert "NEW" in result.output


def test_compare_json(runner, tmp_path):
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    img_a.write_bytes(b"\x89PNG\r\n\x1a\n")
    img_b.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result()

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["compare", str(img_a), str(img_b), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "added" in data
    assert "removed" in data
    assert "changed" in data


# ---------------------------------------------------------------------------
# report-html — functional test with mocked pipeline
# ---------------------------------------------------------------------------

def test_report_html_help(runner):
    result = runner.invoke(main, ["report-html", "--help"])
    assert result.exit_code == 0
    assert "HTML" in result.output or "report" in result.output.lower()


def test_report_html_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    out_file = tmp_path / "report.html"

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.html_report.save_html_report") as mock_save:
        result = runner.invoke(main, ["report-html", str(img), "-o", str(out_file)])
    assert result.exit_code == 0
    assert "Report saved" in result.output
    mock_save.assert_called_once()


def test_report_html_default_output(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.html_report.save_html_report") as mock_save:
        result = runner.invoke(main, ["report-html", str(img)])
    assert result.exit_code == 0
    assert "board_report.html" in result.output


# ---------------------------------------------------------------------------
# report — plain text
# ---------------------------------------------------------------------------

def test_report_plain(runner):
    with patch("retrace.learning.engine.generate_report", return_value="Knowledge base: 42 entries"):
        result = runner.invoke(main, ["report"])
    assert result.exit_code == 0
    assert "42 entries" in result.output


# ---------------------------------------------------------------------------
# scan — success path with mocked pipeline
# ---------------------------------------------------------------------------

def test_scan_success(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["scan", str(img)])
    assert result.exit_code == 0
    assert "components" in result.output.lower() or "U1" in result.output


def test_scan_with_output_dir(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    out_dir = tmp_path / "scan_out"
    mock_result = _make_analysis_result(str(img))

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["scan", str(img), "-o", str(out_dir)])
    assert result.exit_code == 0
    assert "saved" in result.output.lower()


def test_scan_with_bom(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    bom_data = {"components": [{"ref": "U1"}, {"ref": "R1"}]}

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.bom.generate_bom", return_value=bom_data):
        result = runner.invoke(main, ["scan", str(img), "--bom"])
    assert result.exit_code == 0
    assert "2 components" in result.output


def test_scan_quiet(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    out_dir = tmp_path / "quiet_out"
    mock_result = _make_analysis_result(str(img))

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["--quiet", "scan", str(img), "-o", str(out_dir)])
    assert result.exit_code == 0
    assert "saved" not in result.output.lower()


# ---------------------------------------------------------------------------
# export-kicad
# ---------------------------------------------------------------------------

def test_export_kicad_help(runner):
    result = runner.invoke(main, ["export-kicad", "--help"])
    assert result.exit_code == 0
    assert "KiCad" in result.output or "netlist" in result.output.lower()


def test_export_kicad_command(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))
    out_file = tmp_path / "board.net"

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.kicad.save_kicad_netlist") as mock_save:
        result = runner.invoke(main, ["export-kicad", str(img), "-o", str(out_file)])
    assert result.exit_code == 0
    assert "KiCad netlist saved" in result.output
    mock_save.assert_called_once()


def test_export_kicad_default_output(runner, tmp_path):
    img = tmp_path / "board.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_result = _make_analysis_result(str(img))

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.kicad.save_kicad_netlist") as mock_save:
        result = runner.invoke(main, ["export-kicad", str(img)])
    assert result.exit_code == 0
    assert "board.net" in result.output


# ---------------------------------------------------------------------------
# batch command
# ---------------------------------------------------------------------------

def test_batch_help(runner):
    result = runner.invoke(main, ["batch", "--help"])
    assert result.exit_code == 0
    assert "directory" in result.output.lower() or "DIRECTORY" in result.output


def test_batch_command(runner, tmp_path):
    src = tmp_path / "boards"
    src.mkdir()
    (src / "board1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (src / "board2.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    out = tmp_path / "results"

    mock_result = _make_analysis_result("board.png")

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result):
        result = runner.invoke(main, ["batch", str(src), "-o", str(out)])
    assert result.exit_code == 0
    assert "Batch complete" in result.output
    assert "2 boards" in result.output


def test_batch_empty_directory(runner, tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    result = runner.invoke(main, ["batch", str(src)])
    assert result.exit_code != 0


def test_batch_with_report(runner, tmp_path):
    src = tmp_path / "boards"
    src.mkdir()
    (src / "board.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    out = tmp_path / "results"

    mock_result = _make_analysis_result("board.png")

    with patch("retrace.core.pipeline.Pipeline.run", return_value=mock_result), \
         patch("retrace.export.html_report.save_html_report") as mock_report:
        result = runner.invoke(main, ["batch", str(src), "-o", str(out), "--report"])
    assert result.exit_code == 0
    mock_report.assert_called_once()
