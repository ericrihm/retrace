"""Tests that README.md and docs/index.html stats are consistent with the codebase."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.resolve()
README = REPO_ROOT / "README.md"
SHOWCASE = REPO_ROOT / "docs" / "index.html"
SRC_DIR = REPO_ROOT / "src" / "retrace"

_MARKER_RE = re.compile(
    r"<!-- STATS:(?P<key>[a-zA-Z_]+) -->(?P<value>.*?)<!-- /STATS -->",
    re.DOTALL,
)


def _readme_stats() -> dict[str, str]:
    content = README.read_text(encoding="utf-8")
    return {m.group("key"): m.group("value") for m in _MARKER_RE.finditer(content)}


class TestReadmeMarkers:
    def test_markers_exist(self):
        stats = _readme_stats()
        for key in ("tests", "coverage", "loc", "modules", "components", "patterns"):
            assert key in stats, f"Missing <!-- STATS:{key} --> marker in README"

    def test_tests_positive(self):
        stats = _readme_stats()
        assert int(stats["tests"]) > 0

    def test_loc_positive(self):
        stats = _readme_stats()
        assert int(stats["loc"]) > 0

    def test_modules_matches_source(self):
        stats = _readme_stats()
        actual = sum(
            1 for p in SRC_DIR.rglob("*.py")
            if p.name not in ("__init__.py", "__main__.py")
        )
        assert int(stats["modules"]) == actual

    def test_all_markers_consistent(self):
        """All instances of the same STATS marker have the same value."""
        content = README.read_text(encoding="utf-8")
        values_by_key: dict[str, set[str]] = {}
        for m in _MARKER_RE.finditer(content):
            values_by_key.setdefault(m.group("key"), set()).add(m.group("value"))
        for key, values in values_by_key.items():
            assert len(values) == 1, (
                f"STATS:{key} has inconsistent values: {values}"
            )


class TestShowcaseStats:
    @pytest.fixture()
    def showcase_content(self):
        return SHOWCASE.read_text(encoding="utf-8")

    def test_tests_stat_present(self, showcase_content):
        m = re.search(r'<div class="stat-val">(\d+)</div><div class="stat-label">Tests</div>', showcase_content)
        assert m, "Tests stat not found in showcase"
        assert int(m.group(1)) > 0

    def test_coverage_stat_present(self, showcase_content):
        m = re.search(r'<div class="stat-val">(\d+)%</div><div class="stat-label">Coverage</div>', showcase_content)
        assert m, "Coverage stat not found in showcase"
        assert 0 < int(m.group(1)) <= 100

    def test_cli_commands_stat_matches(self, showcase_content):
        m = re.search(r'<div class="stat-val">(\d+)</div><div class="stat-label">CLI Commands</div>', showcase_content)
        assert m, "CLI Commands stat not found in showcase"
        from retrace.cli import main
        actual = len(main.commands)
        assert int(m.group(1)) == actual, (
            f"Showcase says {m.group(1)} CLI commands, actual: {actual}"
        )


class TestExampleFilesExist:
    @pytest.fixture()
    def readme_content(self):
        return README.read_text(encoding="utf-8")

    def test_all_readme_images_exist(self, readme_content):
        for m in re.finditer(r'<img\s+src="([^"]+)"', readme_content):
            path = REPO_ROOT / m.group(1)
            assert path.exists(), f"README references missing image: {m.group(1)}"

    def test_showcase_images_exist(self):
        content = SHOWCASE.read_text(encoding="utf-8")
        examples_dir = REPO_ROOT / "docs"
        for m in re.finditer(r'<img\s+src="([^"]+)"', content):
            href = m.group(1)
            if href.startswith(("http://", "https://", "data:")):
                continue
            path = examples_dir / href
            assert path.exists(), f"Showcase references missing file: {href}"

    def test_showcase_links_exist(self):
        content = SHOWCASE.read_text(encoding="utf-8")
        examples_dir = REPO_ROOT / "docs"
        for m in re.finditer(r'<a\s+href="(examples/[^"]+)"', content):
            path = examples_dir / m.group(1)
            assert path.exists(), f"Showcase links to missing file: {m.group(1)}"
