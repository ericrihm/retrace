"""Tests for entropy SVG heatmap generator."""

from __future__ import annotations

import os

from retrace.analysis.firmware_triage import (
    EntropyBlock,
    MagicMatch,
    TriageResult,
    triage_firmware,
)
from retrace.export.entropy_svg import generate_entropy_svg


def _make_result(**overrides) -> TriageResult:
    defaults = dict(
        file_path="/tmp/test.bin",
        file_size=8192,
        sha256="a" * 64,
        entropy_map=[
            EntropyBlock(offset=0, size=4096, entropy=0.5, classification="null/padding"),
            EntropyBlock(offset=4096, size=4096, entropy=7.8, classification="encrypted/random"),
        ],
        magic_matches=[],
        interesting_strings=[],
        overall_entropy=4.15,
        is_encrypted=False,
        has_filesystem=False,
        has_bootloader=False,
    )
    defaults.update(overrides)
    return TriageResult(**defaults)


class TestEntropySvg:
    def test_basic_output(self):
        svg = generate_entropy_svg(_make_result())
        assert "<svg" in svg
        assert "</svg>" in svg
        assert "Firmware Entropy Map" in svg

    def test_contains_file_info(self):
        svg = generate_entropy_svg(_make_result(file_path="/tmp/router.bin"))
        assert "router.bin" in svg

    def test_contains_sha256(self):
        result = _make_result(sha256="deadbeef" * 8)
        svg = generate_entropy_svg(result)
        assert "deadbeef" in svg

    def test_empty_entropy_map(self):
        result = _make_result(entropy_map=[])
        svg = generate_entropy_svg(result)
        assert svg == ""

    def test_single_block(self):
        result = _make_result(
            entropy_map=[EntropyBlock(offset=0, size=4096, entropy=3.5, classification="code/data")]
        )
        svg = generate_entropy_svg(result)
        assert "<svg" in svg
        assert "code" in svg.lower() or "16537e" in svg

    def test_all_classifications_colored(self):
        blocks = [
            EntropyBlock(offset=0, size=1000, entropy=0.1, classification="null/padding"),
            EntropyBlock(offset=1000, size=1000, entropy=3.0, classification="code/data"),
            EntropyBlock(offset=2000, size=1000, entropy=5.0, classification="text/structured"),
            EntropyBlock(offset=3000, size=1000, entropy=7.0, classification="compressed"),
            EntropyBlock(offset=4000, size=1000, entropy=7.9, classification="encrypted/random"),
        ]
        svg = generate_entropy_svg(_make_result(entropy_map=blocks))
        assert "#1a1a2e" in svg  # null
        assert "#16537e" in svg  # code
        assert "#2d6a4f" in svg  # text
        assert "#b5651d" in svg  # compressed
        assert "#9b2226" in svg  # encrypted

    def test_magic_markers(self):
        result = _make_result(
            magic_matches=[
                MagicMatch(offset=100, signature="ELF", description="ELF executable"),
                MagicMatch(offset=4000, signature="gzip", description="gzip compressed"),
            ]
        )
        svg = generate_entropy_svg(result)
        assert "ELF" in svg
        assert "gzip" in svg

    def test_encrypted_flag(self):
        svg = generate_entropy_svg(_make_result(is_encrypted=True))
        assert "ENCRYPTED" in svg

    def test_bootloader_flag(self):
        svg = generate_entropy_svg(_make_result(has_bootloader=True))
        assert "Bootloader" in svg

    def test_filesystem_flag(self):
        svg = generate_entropy_svg(_make_result(has_filesystem=True))
        assert "Filesystem" in svg

    def test_legend_present(self):
        svg = generate_entropy_svg(_make_result())
        assert "Null / Padding" in svg
        assert "Code / Data" in svg
        assert "Encrypted / Random" in svg

    def test_custom_width(self):
        svg = generate_entropy_svg(_make_result(), width=600)
        assert 'viewBox="0 0 600' in svg

    def test_x_axis_labels(self):
        svg = generate_entropy_svg(_make_result(file_size=8192))
        assert "0x00000000" in svg

    def test_overall_entropy(self):
        svg = generate_entropy_svg(_make_result(overall_entropy=5.123))
        assert "5.123" in svg

    def test_polyline_for_multiple_blocks(self):
        blocks = [
            EntropyBlock(offset=i * 100, size=100, entropy=float(i), classification="code/data")
            for i in range(5)
        ]
        svg = generate_entropy_svg(_make_result(entropy_map=blocks))
        assert "polyline" in svg

    def test_integration_with_triage(self, tmp_path):
        fw = tmp_path / "test.bin"
        fw.write_bytes(b"\x7fELF" + b"\x00" * 4092 + os.urandom(4096))
        result = triage_firmware(fw)
        svg = generate_entropy_svg(result)
        assert "<svg" in svg
        assert "ELF" in svg

    def test_many_magic_matches_capped(self):
        matches = [
            MagicMatch(offset=i * 100, signature=f"SIG{i}", description=f"sig {i}")
            for i in range(30)
        ]
        result = _make_result(magic_matches=matches)
        svg = generate_entropy_svg(result)
        sig_count = svg.count("SIG")
        assert sig_count <= 15
