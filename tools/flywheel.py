#!/usr/bin/env python3
"""
flywheel.py — codexbro flywheel runner for the retrace PCB RE toolkit.

Orchestrates all improvement flywheels to continuously improve the repo's
visual showcase. Safe to run repeatedly (idempotent).

Usage:
    python tools/flywheel.py run            # Run all flywheels
    python tools/flywheel.py run --quick    # Stats + lint only (fast)
    python tools/flywheel.py status         # Show flywheel health
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR = REPO_ROOT / "src" / "retrace"
TESTS_DIR = REPO_ROOT / "tests"
STATE_FILE = REPO_ROOT / ".flywheel_state.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess, always capturing output."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        **kwargs,
    )


def _header(title: str) -> None:
    click.echo("")
    click.echo(click.style(f"── {title} ", fg="cyan", bold=True) + click.style("─" * (60 - len(title)), fg="cyan"))


def _ok(msg: str) -> None:
    click.echo(click.style("  ✓ ", fg="green") + msg)


def _warn(msg: str) -> None:
    click.echo(click.style("  ⚠ ", fg="yellow") + msg)


def _err(msg: str) -> None:
    click.echo(click.style("  ✗ ", fg="red") + msg)


def _info(msg: str) -> None:
    click.echo(click.style("  · ", fg="bright_black") + msg)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Flywheel 1: Stats
# ---------------------------------------------------------------------------


def flywheel_stats() -> bool:
    """Run readme_stats.py update to keep README numbers current."""
    _header("Stats flywheel — update README metrics")
    stats_script = REPO_ROOT / "tools" / "readme_stats.py"
    if not stats_script.exists():
        _warn("tools/readme_stats.py not found — skipping")
        return True

    result = _run([sys.executable, str(stats_script), "update"])
    if result.returncode == 0:
        _ok("README stats updated")
        for line in result.stdout.splitlines():
            if line.strip():
                _info(line.strip())
        return True
    else:
        _warn(f"readme_stats.py exited {result.returncode}")
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                _info(line.strip())
        return True  # non-fatal — stats update failures don't fail the run


# ---------------------------------------------------------------------------
# Flywheel 2: Lint
# ---------------------------------------------------------------------------


def flywheel_lint() -> tuple[bool, int]:
    """Run ruff check --fix and stage auto-fixed files."""
    _header("Lint flywheel — ruff auto-fix")
    result = _run(["ruff", "check", "src/", "tests/", "--fix"])
    fixed_count = 0
    for line in result.stdout.splitlines():
        m = re.search(r"Fixed (\d+) error", line)
        if m:
            fixed_count = int(m.group(1))

    if result.returncode == 0:
        if fixed_count:
            _ok(f"Ruff auto-fixed {fixed_count} issue(s)")
            # Stage the fixed files
            stage = _run(["git", "add", "src/", "tests/"])
            if stage.returncode == 0:
                _info("Staged lint-fixed files (not committed)")
            else:
                _warn("git add failed — manual staging needed")
        else:
            _ok("No lint issues found")
        return True, fixed_count
    else:
        # Remaining violations that couldn't be auto-fixed
        remaining = [l for l in result.stdout.splitlines() if l.strip() and "error" in l.lower()]
        _warn(f"Ruff found un-fixable violations (exit {result.returncode})")
        for line in result.stdout.splitlines()[:10]:
            if line.strip():
                _info(line.strip())
        return True, fixed_count  # lint failures are warnings, not fatal


# ---------------------------------------------------------------------------
# Flywheel 3: Tests
# ---------------------------------------------------------------------------


def flywheel_tests() -> tuple[bool, int, int, list[str]]:
    """Run pytest and report pass/fail counts."""
    _header("Test flywheel — pytest")
    result = _run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"])

    passed = failed = 0
    failed_tests: list[str] = []

    for line in result.stdout.splitlines():
        # "3 failed, 47 passed in 4.21s"
        m = re.search(r"(\d+) failed", line)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+) passed", line)
        if m:
            passed = int(m.group(1))
        # Collect FAILED lines: "FAILED tests/test_foo.py::test_bar - ..."
        if line.strip().startswith("FAILED "):
            test_id = line.strip().split()[1]
            failed_tests.append(test_id)

    total = passed + failed
    if failed == 0 and total > 0:
        _ok(f"All {passed} tests passed")
        return True, passed, failed, []
    elif failed == 0 and total == 0:
        _warn("No tests collected")
        return True, 0, 0, []
    else:
        _err(f"{failed}/{total} tests FAILED")
        for t in failed_tests[:20]:
            _info(f"  FAILED: {t}")
        if len(failed_tests) > 20:
            _info(f"  ... and {len(failed_tests) - 20} more")
        # Print short tb summary
        in_tb = False
        for line in result.stdout.splitlines():
            if line.startswith("FAILED") or line.startswith("_ "):
                in_tb = True
            if in_tb and line.strip():
                _info(line)
        return False, passed, failed, failed_tests


# ---------------------------------------------------------------------------
# Flywheel 4: Demo generation
# ---------------------------------------------------------------------------


def flywheel_demo() -> bool:
    """Regenerate visual outputs via generate_demo.py (if present)."""
    _header("Demo flywheel — regenerate visual outputs")
    demo_script = REPO_ROOT / "tools" / "generate_demo.py"
    if not demo_script.exists():
        _info("tools/generate_demo.py not present yet — skipping gracefully")
        return True

    result = _run([sys.executable, str(demo_script), "generate"])
    if result.returncode == 0:
        _ok("Demo assets regenerated")
        for line in result.stdout.splitlines():
            if line.strip():
                _info(line.strip())
        # Stage generated assets
        _run(["git", "add", "docs/", "demo/", "assets/"])
        return True
    else:
        _warn(f"generate_demo.py failed (exit {result.returncode})")
        for line in (result.stdout + result.stderr).splitlines()[:10]:
            if line.strip():
                _info(line.strip())
        return True  # non-fatal


# ---------------------------------------------------------------------------
# Flywheel 5: Coverage
# ---------------------------------------------------------------------------


def flywheel_coverage(state: dict) -> tuple[bool, str]:
    """Run pytest --cov and warn if coverage dropped."""
    _header("Coverage flywheel — measure and track")
    result = _run([
        sys.executable, "-m", "pytest",
        "--cov=retrace", "--cov-report=term",
        "-q", "--tb=no", "--no-header",
    ])

    combined = result.stdout + result.stderr
    coverage_pct: str = "N/A"
    dropped = False

    m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", combined, re.MULTILINE)
    if m:
        coverage_pct = m.group(1) + "%"
        current_val = int(m.group(1))
        prev_raw = state.get("coverage_pct", "N/A")
        if prev_raw != "N/A":
            prev_val = int(prev_raw.rstrip("%"))
            if current_val < prev_val:
                dropped = True
                _warn(
                    f"Coverage DROPPED: {prev_val}% → {current_val}%  "
                    f"(delta: {current_val - prev_val}%)"
                )
            elif current_val > prev_val:
                _ok(f"Coverage improved: {prev_val}% → {current_val}%")
            else:
                _ok(f"Coverage stable at {current_val}%")
        else:
            _ok(f"Coverage: {current_val}% (baseline established)")
    else:
        _warn("Could not parse coverage from pytest output")
        for line in combined.splitlines()[-20:]:
            if "TOTAL" in line or "error" in line.lower():
                _info(line.strip())

    return not dropped, coverage_pct


# ---------------------------------------------------------------------------
# Flywheel 6: Gap analysis
# ---------------------------------------------------------------------------


def flywheel_gaps(coverage_output: str = "") -> dict:
    """Analyze the codebase for quality gaps."""
    _header("Gap analysis flywheel — quality gaps")
    gaps: dict = {
        "zero_coverage_modules": [],
        "untested_sources": [],
        "todo_count": 0,
        "todo_locations": [],
        "untyped_functions": [],
    }

    # -- 6a. Zero-coverage modules --
    result = _run([
        sys.executable, "-m", "pytest",
        "--cov=retrace", "--cov-report=term",
        "-q", "--tb=no", "--no-header",
    ])
    combined = result.stdout + result.stderr
    zero_cov: list[str] = []
    for line in combined.splitlines():
        # Lines look like: "retrace/cli.py    120     85    29%   ..."
        m = re.match(r"\s*(retrace[\w/\\\.]+\.py)\s+\d+\s+\d+\s+0%", line)
        if m:
            zero_cov.append(m.group(1))
    gaps["zero_coverage_modules"] = zero_cov
    if zero_cov:
        _warn(f"Modules at 0% coverage ({len(zero_cov)}):")
        for mod in zero_cov:
            _info(f"  {mod}")
    else:
        _ok("No modules at 0% coverage")

    # -- 6b. Source files without test files --
    src_modules: list[str] = []
    for src_file in SRC_DIR.rglob("*.py"):
        if src_file.name == "__init__.py":
            continue
        # Compute expected test file name
        rel = src_file.relative_to(SRC_DIR)
        # e.g. analysis/cross_board.py → test_cross_board.py
        stem = src_file.stem
        expected_test = TESTS_DIR / f"test_{stem}.py"
        if not expected_test.exists():
            src_modules.append(str(src_file.relative_to(REPO_ROOT)))
    gaps["untested_sources"] = src_modules
    if src_modules:
        _warn(f"Source files without corresponding tests ({len(src_modules)}):")
        for s in src_modules:
            _info(f"  {s}")
    else:
        _ok("All source modules have test files")

    # -- 6c. TODO/FIXME/HACK/XXX/WORKAROUND comments --
    todo_pattern = re.compile(r"#.*\b(TODO|FIXME|HACK|XXX|WORKAROUND)\b", re.IGNORECASE)
    todo_locations: list[str] = []
    for py_file in SRC_DIR.rglob("*.py"):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if todo_pattern.search(line):
                    rel_path = str(py_file.relative_to(REPO_ROOT))
                    todo_locations.append(f"{rel_path}:{i}")
        except Exception:
            pass
    gaps["todo_count"] = len(todo_locations)
    gaps["todo_locations"] = todo_locations[:50]  # cap for state file
    if todo_locations:
        _warn(f"TODO/FIXME/HACK comments in source: {len(todo_locations)}")
        for loc in todo_locations[:10]:
            _info(f"  {loc}")
        if len(todo_locations) > 10:
            _info(f"  ... and {len(todo_locations) - 10} more")
    else:
        _ok("No TODO/FIXME/HACK comments in source")

    # -- 6d. Functions without type hints --
    untyped: list[str] = []
    for py_file in SRC_DIR.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Skip private/dunder methods and test helpers
                    if node.name.startswith("_"):
                        continue
                    missing_return = node.returns is None
                    missing_args = any(
                        arg.annotation is None
                        for arg in node.args.args
                        if arg.arg != "self"
                    )
                    if missing_return or missing_args:
                        rel = str(py_file.relative_to(REPO_ROOT))
                        untyped.append(f"{rel}:{node.lineno} {node.name}()")
        except Exception:
            pass
    gaps["untyped_functions"] = untyped[:50]
    if untyped:
        _warn(f"Public functions missing type hints: {len(untyped)}")
        for fn in untyped[:8]:
            _info(f"  {fn}")
        if len(untyped) > 8:
            _info(f"  ... and {len(untyped) - 8} more")
    else:
        _ok("All public functions have type hints")

    return gaps


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """retrace flywheel runner — orchestrate continuous improvement loops."""


@cli.command()
@click.option(
    "--quick",
    is_flag=True,
    default=False,
    help="Run stats + lint only (fast — skip tests, coverage, gaps).",
)
def run(quick: bool) -> None:
    """Run all improvement flywheels (or --quick subset)."""
    click.echo(click.style("\nretrace flywheel runner", fg="magenta", bold=True))
    click.echo(click.style(f"{'Quick mode' if quick else 'Full mode'} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fg="bright_black"))

    state = _load_state()
    all_passed = True
    metrics: dict = {}

    # 1. Stats
    flywheel_stats()

    # 2. Lint
    lint_ok, fixed = flywheel_lint()
    metrics["lint_fixed"] = fixed

    if not quick:
        # 3. Tests
        tests_ok, passed, failed, failed_tests = flywheel_tests()
        metrics["tests_passed"] = passed
        metrics["tests_failed"] = failed
        metrics["failed_test_ids"] = failed_tests
        if not tests_ok:
            all_passed = False

        # 4. Demo
        flywheel_demo()

        # 5. Coverage
        cov_ok, coverage_pct = flywheel_coverage(state)
        metrics["coverage_pct"] = coverage_pct
        if not cov_ok:
            _warn("Coverage regression detected — flagging (not failing run)")

        # 6. Gap analysis
        gaps = flywheel_gaps()
        metrics.update({
            "zero_coverage_count": len(gaps["zero_coverage_modules"]),
            "untested_source_count": len(gaps["untested_sources"]),
            "todo_count": gaps["todo_count"],
            "untyped_function_count": len(gaps["untyped_functions"]),
        })
    else:
        coverage_pct = state.get("coverage_pct", "N/A")
        metrics["coverage_pct"] = coverage_pct

    # Persist state
    now_iso = datetime.now(timezone.utc).isoformat()
    state["last_run"] = now_iso
    state["last_mode"] = "quick" if quick else "full"
    state.update(metrics)
    _save_state(state)

    # Summary
    _header("Summary")
    if all_passed:
        click.echo(click.style("\n  Flywheel run complete — all checks passed.\n", fg="green", bold=True))
    else:
        click.echo(click.style("\n  Flywheel run complete — tests FAILED.\n", fg="red", bold=True))

    if not quick:
        _info(f"Tests:    {metrics.get('tests_passed', '?')} passed, {metrics.get('tests_failed', '?')} failed")
        _info(f"Coverage: {metrics.get('coverage_pct', 'N/A')}")
        _info(f"Lint:     {fixed} fix(es) applied")
        _info(f"TODOs:    {metrics.get('todo_count', '?')} in source")
        _info(f"Untyped:  {metrics.get('untyped_function_count', '?')} public functions")
    else:
        _info(f"Lint: {fixed} fix(es) applied  (quick mode — tests skipped)")

    click.echo("")
    sys.exit(0 if all_passed else 1)


@cli.command()
def status() -> None:
    """Show flywheel health: last run, current metrics, outstanding gaps."""
    click.echo(click.style("\nretrace flywheel status", fg="magenta", bold=True))
    click.echo("")

    state = _load_state()

    if not state:
        click.echo(click.style("  No flywheel state found.", fg="yellow"))
        click.echo("  Run:  python tools/flywheel.py run")
        click.echo("")
        return

    last_run = state.get("last_run", "never")
    last_mode = state.get("last_mode", "?")
    click.echo(click.style("  Last run:", bold=True) + f"  {last_run}  [{last_mode} mode]")
    click.echo("")

    click.echo(click.style("  Metrics:", bold=True))
    _info(f"Tests:       {state.get('tests_passed', 'N/A')} passed, {state.get('tests_failed', 'N/A')} failed")
    _info(f"Coverage:    {state.get('coverage_pct', 'N/A')}")
    _info(f"Lint fixes:  {state.get('lint_fixed', 'N/A')} (last run)")
    click.echo("")

    click.echo(click.style("  Outstanding gaps:", bold=True))
    zero_cov = state.get("zero_coverage_count", "N/A")
    untested = state.get("untested_source_count", "N/A")
    todos = state.get("todo_count", "N/A")
    untyped = state.get("untyped_function_count", "N/A")

    zero_cov_style = "red" if isinstance(zero_cov, int) and zero_cov > 0 else "green"
    untested_style = "yellow" if isinstance(untested, int) and untested > 0 else "green"
    todos_style = "yellow" if isinstance(todos, int) and todos > 0 else "green"
    untyped_style = "yellow" if isinstance(untyped, int) and untyped > 0 else "green"

    _info(f"0% coverage modules: {click.style(str(zero_cov), fg=zero_cov_style)}")
    _info(f"Untested sources:    {click.style(str(untested), fg=untested_style)}")
    _info(f"TODO/FIXME comments: {click.style(str(todos), fg=todos_style)}")
    _info(f"Untyped functions:   {click.style(str(untyped), fg=untyped_style)}")

    # Warn about failed tests from last run
    failed_ids = state.get("failed_test_ids", [])
    if failed_ids:
        click.echo("")
        click.echo(click.style("  Failed tests (last run):", bold=True, fg="red"))
        for t in failed_ids[:10]:
            _err(t)
        if len(failed_ids) > 10:
            _info(f"  ... and {len(failed_ids) - 10} more")

    click.echo("")


if __name__ == "__main__":
    cli()
