#!/usr/bin/env python3
"""
readme_stats.py — auto-update dynamic stats markers in README.md.

Markers in README.md look like:
    <!-- STATS:key -->value<!-- /STATS -->

Run this script periodically (codexbro flywheel) to keep numbers current.

Usage:
    python tools/readme_stats.py update
    python tools/readme_stats.py update --dry-run
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Paths (resolved relative to this script's location so it works from any cwd)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.resolve()
README = REPO_ROOT / "README.md"
SRC_DIR = REPO_ROOT / "src" / "retrace"


# ---------------------------------------------------------------------------
# Stat collectors
# ---------------------------------------------------------------------------

def _collect_pytest_stats() -> tuple[int, str]:
    """Return (total_test_count, coverage_pct_string).

    Runs pytest twice: once for collection count, once for coverage.
    Returns ("0", "N/A") on failure so the script never crashes.
    """
    # --- test count ---
    test_count = 0
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        # Last non-empty line: "67 tests collected in 0.23s" or "no tests ran"
        for line in reversed(result.stdout.splitlines()):
            line = line.strip()
            m = re.match(r"(\d+)\s+tests?\s+collected", line)
            if m:
                test_count = int(m.group(1))
                break
    except Exception:
        pass

    # --- coverage ---
    coverage_pct = "N/A"
    try:
        cov_result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "--cov=retrace", "--cov-report=term",
                "-q", "--no-header", "--tb=no",
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        output = cov_result.stdout + cov_result.stderr
        # Look for "TOTAL  ... XX%"
        m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", output, re.MULTILINE)
        if m:
            coverage_pct = m.group(1) + "%"
    except Exception:
        pass

    return test_count, coverage_pct


def _collect_loc() -> int:
    """Return total lines of Python source code under src/retrace."""
    try:
        find = subprocess.run(
            ["find", str(SRC_DIR), "-name", "*.py"],
            capture_output=True, text=True,
        )
        py_files = [f for f in find.stdout.splitlines() if f.strip()]
        if not py_files:
            return 0
        wc = subprocess.run(
            ["wc", "-l"] + py_files,
            capture_output=True, text=True,
        )
        # Last line is the "total" line when multiple files
        for line in reversed(wc.stdout.splitlines()):
            line = line.strip()
            m = re.match(r"(\d+)\s+(?:total|/|$)", line)
            if m:
                return int(m.group(1))
            # single-file: just "NNN path"
            m = re.match(r"(\d+)\s+", line)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0


def _collect_modules() -> int:
    """Count non-__init__.py .py files in src/retrace."""
    return sum(
        1
        for p in SRC_DIR.rglob("*.py")
        if p.name != "__init__.py"
    )


def _collect_component_db_size() -> int:
    """Import matcher and count entries in _COMPONENT_DB."""
    try:
        # Make sure src/ is importable
        src_path = str(REPO_ROOT / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        import importlib
        mod = importlib.import_module("retrace.identification.matcher")
        db: list = getattr(mod, "_COMPONENT_DB", [])
        return len(db)
    except Exception:
        return 0


def _collect_cross_board_patterns() -> int:
    """Import CrossBoardEngine and count built-in patterns."""
    try:
        src_path = str(REPO_ROOT / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        import importlib
        mod = importlib.import_module("retrace.analysis.cross_board")
        fn = getattr(mod, "_builtin_patterns", None)
        if fn is not None:
            return len(fn())
        # Fallback: instantiate the engine
        engine_cls = getattr(mod, "CrossBoardEngine", None)
        if engine_cls is not None:
            engine = engine_cls()
            return len(engine.list_patterns())
    except Exception:
        pass
    return 0


def _collect_debug_signatures() -> int:
    """Import debug_interfaces and count entries in _INTERFACE_PATTERNS."""
    try:
        src_path = str(REPO_ROOT / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        import importlib
        mod = importlib.import_module("retrace.plugins.builtin.debug_interfaces")
        patterns: dict = getattr(mod, "_INTERFACE_PATTERNS", {})
        return len(patterns)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# README update logic
# ---------------------------------------------------------------------------

# Matches:  <!-- STATS:key -->anything<!-- /STATS -->
_MARKER_RE = re.compile(
    r"<!-- STATS:(?P<key>[a-zA-Z_]+) -->(?P<value>.*?)<!-- /STATS -->",
    re.DOTALL,
)


def _gather_stats() -> dict[str, str]:
    """Collect all stats and return a key→value mapping."""
    click.echo("  Collecting test count and coverage (running pytest)...")
    test_count, coverage = _collect_pytest_stats()

    click.echo("  Counting lines of code...")
    loc = _collect_loc()

    click.echo("  Counting modules...")
    modules = _collect_modules()

    click.echo("  Counting component DB entries...")
    components = _collect_component_db_size()

    click.echo("  Counting cross-board patterns...")
    patterns = _collect_cross_board_patterns()

    # debug signatures collected via import (fast, no subprocess)
    debug_sigs = _collect_debug_signatures()

    return {
        "tests": str(test_count),
        "coverage": coverage,
        "loc": str(loc),
        "modules": str(modules),
        "components": str(components),
        "patterns": str(patterns),
        # exposed for completeness but no required marker defined
        "debug_signatures": str(debug_sigs),
    }


def _apply_stats(content: str, stats: dict[str, str]) -> tuple[str, list[str]]:
    """Replace STATS markers in *content* with values from *stats*.

    Returns (new_content, list_of_changed_keys).
    """
    changed: list[str] = []

    def replacer(m: re.Match) -> str:
        key = m.group("key")
        old_value = m.group("value")
        new_value = stats.get(key, old_value)  # keep existing if key unknown
        if new_value != old_value:
            changed.append(key)
        return f"<!-- STATS:{key} -->{new_value}<!-- /STATS -->"

    new_content = _MARKER_RE.sub(replacer, content)

    cov_str = stats.get("coverage", "")
    cov_m = re.match(r"(\d+)%", cov_str)
    if cov_m:
        pct = int(cov_m.group(1))
        color = "brightgreen" if pct >= 90 else "green" if pct >= 80 else "yellowgreen" if pct >= 70 else "yellow" if pct >= 60 else "red"
        badge_re = re.compile(r"coverage-\d+%25-\w+\.svg")
        new_badge = f"coverage-{pct}%25-{color}.svg"
        if badge_re.search(new_content) and badge_re.search(new_content).group() != new_badge:
            new_content = badge_re.sub(new_badge, new_content)
            if "coverage_badge" not in changed:
                changed.append("coverage_badge")

    return new_content, changed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """readme_stats — keep README.md stats current."""


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print changes without writing the file.")
@click.option(
    "--readme",
    default=str(README),
    show_default=True,
    help="Path to README.md to update.",
)
def update(dry_run: bool, readme: str) -> None:
    """Collect current stats and update STATS markers in README.md."""
    readme_path = Path(readme)
    if not readme_path.exists():
        click.echo(f"ERROR: README not found at {readme_path}", err=True)
        sys.exit(1)

    click.echo("Gathering stats...")
    stats = _gather_stats()
    click.echo("  Done.")
    click.echo("")

    content = readme_path.read_text(encoding="utf-8")
    new_content, changed = _apply_stats(content, stats)

    # Report what markers exist and what their new values are
    found_keys = [m.group("key") for m in _MARKER_RE.finditer(content)]
    if not found_keys:
        click.echo("No <!-- STATS:... --> markers found in README.md.")
        click.echo("Add markers like:  <!-- STATS:tests -->0<!-- /STATS -->")
        sys.exit(0)

    for key in found_keys:
        key_re = re.compile(
            rf"<!-- STATS:{re.escape(key)} -->(?P<v>.*?)<!-- /STATS -->",
            re.DOTALL,
        )
        old_match = key_re.search(content)
        old_val = old_match.group("v") if old_match else "?"
        new_val = stats.get(key, old_val)
        status = " (changed)" if key in changed else " (unchanged)"
        click.echo(f"  {key}: {old_val!r} -> {new_val!r}{status}")

    click.echo("")

    if not changed:
        click.echo("All stats are already up to date. No changes written.")
        sys.exit(0)

    if dry_run:
        click.echo(f"[dry-run] Would update {len(changed)} marker(s): {', '.join(changed)}")
        sys.exit(0)

    readme_path.write_text(new_content, encoding="utf-8")
    click.echo(f"Updated README.md — {len(changed)} marker(s) changed: {', '.join(changed)}")
    sys.exit(0)


SHOWCASE = REPO_ROOT / "docs" / "index.html"

_SHOWCASE_PATTERNS = {
    "tests": (re.compile(r'(<div class="stat-val">)\d+(</div><div class="stat-label">Tests</div>)'), r"\g<1>{val}\g<2>"),
    "coverage": (re.compile(r'(<div class="stat-val">)\d+%(</div><div class="stat-label">Coverage</div>)'), r"\g<1>{val}\g<2>"),
    "cli_commands": (re.compile(r'(<div class="stat-val">)\d+(</div><div class="stat-label">CLI Commands</div>)'), r"\g<1>{val}\g<2>"),
}


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def sync_showcase(dry_run: bool) -> None:
    """Sync showcase page (docs/index.html) stats with current values."""
    if not SHOWCASE.exists():
        click.echo(f"ERROR: {SHOWCASE} not found", err=True)
        sys.exit(1)

    click.echo("Gathering stats for showcase...")
    stats = _gather_stats()

    cli_count = 0
    try:
        src_path = str(REPO_ROOT / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        from retrace.cli import main as cli_main
        cli_count = len(cli_main.commands)
    except Exception:
        pass

    content = SHOWCASE.read_text(encoding="utf-8")
    changed: list[str] = []

    updates = {
        "tests": stats.get("tests", "0"),
        "coverage": stats.get("coverage", "N/A"),
        "cli_commands": str(cli_count),
    }

    for key, (pattern, template) in _SHOWCASE_PATTERNS.items():
        val = updates.get(key, "")
        if not val:
            continue
        replacement = template.replace("{val}", val)
        new_content = pattern.sub(replacement, content)
        if new_content != content:
            changed.append(key)
            content = new_content

    for key in updates:
        status = " (changed)" if key in changed else " (unchanged)"
        click.echo(f"  {key}: {updates[key]}{status}")

    if not changed:
        click.echo("Showcase stats already up to date.")
        sys.exit(0)

    if dry_run:
        click.echo(f"[dry-run] Would update {len(changed)} stat(s) in showcase")
        sys.exit(0)

    SHOWCASE.write_text(content, encoding="utf-8")
    click.echo(f"Updated {SHOWCASE.name} — {len(changed)} stat(s) changed")


@cli.command()
def design() -> None:
    """Run the design psychology audit on README.md."""
    try:
        from flywheel import flywheel_design_audit
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from flywheel import flywheel_design_audit

    result = flywheel_design_audit()
    sys.exit(0 if result.get("design_pct", 0) >= 80 else 1)


if __name__ == "__main__":
    cli()
