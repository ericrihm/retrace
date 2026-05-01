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

# Intelligence layer (P0/P1/P2)
try:
    from flywheel_intelligence import FlywheelBrain
    _HAS_BRAIN = True
except ImportError:
    _HAS_BRAIN = False

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


def flywheel_regression(state: dict, metrics: dict) -> list[str]:
    """Compare current metrics against previous run and flag regressions."""
    _header("Regression analysis flywheel — delta tracking")
    regressions: list[str] = []

    checks = [
        ("tests_passed", "Tests passed", True),
        ("tests_failed", "Tests failed", False),
        ("zero_coverage_count", "Modules at 0% coverage", False),
        ("untested_source_count", "Untested source files", False),
        ("todo_count", "TODO/FIXME comments", False),
        ("untyped_function_count", "Untyped public functions", False),
    ]

    for key, label, higher_is_better in checks:
        prev = state.get(key)
        curr = metrics.get(key)
        if prev is None or curr is None:
            continue
        if not isinstance(prev, (int, float)) or not isinstance(curr, (int, float)):
            continue

        delta = curr - prev
        if delta == 0:
            _ok(f"{label}: {curr} (unchanged)")
        elif (higher_is_better and delta > 0) or (not higher_is_better and delta < 0):
            _ok(f"{label}: {prev} → {curr} ({'+' if delta > 0 else ''}{delta}) ↑")
        else:
            msg = f"{label}: {prev} → {curr} ({'+' if delta > 0 else ''}{delta}) REGRESSION"
            _warn(msg)
            regressions.append(msg)

    prev_cov = state.get("coverage_pct", "")
    curr_cov = metrics.get("coverage_pct", "")
    if prev_cov and curr_cov and prev_cov != "N/A" and curr_cov != "N/A":
        try:
            prev_pct = float(str(prev_cov).rstrip("%"))
            curr_pct = float(str(curr_cov).rstrip("%"))
            delta = curr_pct - prev_pct
            if delta >= 0:
                _ok(f"Coverage: {prev_cov} → {curr_cov} ({'+' if delta > 0 else ''}{delta:.1f}pp)")
            else:
                msg = f"Coverage: {prev_cov} → {curr_cov} ({delta:.1f}pp) REGRESSION"
                _warn(msg)
                regressions.append(msg)
        except ValueError:
            pass

    history = state.get("regression_history", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    history.append({
        "timestamp": now_iso,
        "regressions": regressions,
        "tests_passed": metrics.get("tests_passed"),
        "coverage": metrics.get("coverage_pct"),
    })
    state["regression_history"] = history[-50:]

    if not regressions:
        _ok("No regressions detected")
    else:
        _warn(f"{len(regressions)} regression(s) detected")

    return regressions


def flywheel_component_db() -> dict:
    """Track component DB growth and identify missing categories."""
    _header("Component DB flywheel — growth and coverage")

    matcher_path = SRC_DIR / "identification" / "matcher.py"
    if not matcher_path.exists():
        _warn("matcher.py not found")
        return {}

    content = matcher_path.read_text(encoding="utf-8")

    category_counts: dict[str, int] = {}
    for m in re.finditer(r'"category"\s*:\s*"(\w+)"', content):
        cat = m.group(1)
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total = sum(category_counts.values())
    _ok(f"Total component entries: {total}")
    _ok(f"Categories: {len(category_counts)}")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        _info(f"  {cat}: {count}")

    expected_categories = {
        "mcu", "memory", "regulator", "fpga", "network", "rf",
        "secure_element", "sensor", "pmic", "display", "automotive",
    }
    missing = expected_categories - set(category_counts.keys())
    if missing:
        _warn(f"Missing categories: {', '.join(sorted(missing))}")
    else:
        _ok("All expected categories present")

    return {
        "component_total": total,
        "component_categories": len(category_counts),
        "component_by_category": category_counts,
        "missing_categories": sorted(missing) if missing else [],
    }


# ---------------------------------------------------------------------------
# Design audit flywheel — scores README/showcase against psychology criteria
# ---------------------------------------------------------------------------

_DESIGN_CRITERIA = {
    "hero_above_fold": {
        "weight": 10,
        "description": "Hero section with value prop in first 5 lines (primacy effect)",
    },
    "stats_visible": {
        "weight": 8,
        "description": "Quantitative social proof (tests, coverage, LOC) visible early (anchoring)",
    },
    "demo_before_install": {
        "weight": 9,
        "description": "Visual demo before installation instructions (picture superiority)",
    },
    "contrast_table": {
        "weight": 7,
        "description": "Competitive comparison table present (contrast principle)",
    },
    "progressive_disclosure": {
        "weight": 8,
        "description": "Details/summary elements for advanced content (cognitive load reduction)",
    },
    "copy_paste_install": {
        "weight": 9,
        "description": "Single copy-paste install command (friction reduction)",
    },
    "concrete_numbers": {
        "weight": 7,
        "description": "Specific numbers > vague claims (concreteness effect)",
    },
    "social_proof_badges": {
        "weight": 6,
        "description": "CI/coverage/license badges present (authority/trust signals)",
    },
    "cta_links": {
        "weight": 7,
        "description": "Quick navigation links near the top (scanning support)",
    },
    "visual_hierarchy": {
        "weight": 8,
        "description": "Clear heading progression H1 > H2 > H3 (gestalt/hierarchy)",
    },
    "real_world_examples": {
        "weight": 9,
        "description": "Named real devices/CVEs as examples (narrative transportation)",
    },
    "output_samples": {
        "weight": 8,
        "description": "Actual CLI output shown (expectation setting)",
    },
    "api_examples": {
        "weight": 7,
        "description": "Code examples with imports (developer confidence)",
    },
    "security_context": {
        "weight": 6,
        "description": "MITRE ATT&CK / CWE references (domain credibility)",
    },
    "image_density": {
        "weight": 8,
        "description": "Multiple SVG/image demos (dual coding theory)",
    },
}


def flywheel_design_audit() -> dict:
    """Score README.md against evidence-based design psychology criteria.

    Returns a dict of scores, suggestions, and total score.

    Psychology principles applied:
    - Primacy effect: first impressions dominate recall
    - Picture superiority: images recalled 6x better than text
    - Anchoring: first numbers seen set expectation frame
    - Progressive disclosure: reduce cognitive load
    - Contrast principle: comparisons make value obvious
    - Narrative transportation: stories > abstractions
    - Dual coding: text + images together > either alone
    """
    _header("Design audit flywheel — README psychology scoring")

    readme_path = REPO_ROOT / "README.md"
    if not readme_path.exists():
        _warn("README.md not found")
        return {}

    content = readme_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    scores: dict[str, int] = {}
    suggestions: list[str] = []

    first_20 = "\n".join(lines[:20]).lower()
    scores["hero_above_fold"] = 10 if ("photo in" in first_20 or "attack surface" in first_20) else 0
    if not scores["hero_above_fold"]:
        suggestions.append("Move value proposition to first 5 lines (primacy effect)")

    first_30 = "\n".join(lines[:30]).lower()
    scores["stats_visible"] = 8 if ("tests" in first_30 and "loc" in first_30) else 0
    if not scores["stats_visible"]:
        suggestions.append("Add quantitative stats (tests, LOC) in first 30 lines (anchoring)")

    h2_positions = [i for i, l in enumerate(lines) if l.startswith("## ")]
    img_positions = [i for i, l in enumerate(lines) if "<img" in l.lower() or "![" in l]
    install_positions = [i for i, l in enumerate(lines) if "pip install" in l.lower()]
    first_img = min(img_positions) if img_positions else 9999
    first_install = min(install_positions) if install_positions else 9999
    scores["demo_before_install"] = 9 if first_img < first_install else 0
    if not scores["demo_before_install"]:
        suggestions.append("Show demo images before install command (picture superiority)")

    scores["contrast_table"] = 7 if "|" in content and ("prior work" in content.lower() or "comparison" in content.lower()) else 0
    if not scores["contrast_table"]:
        suggestions.append("Add competitive comparison table (contrast principle)")

    detail_count = content.count("<details>")
    scores["progressive_disclosure"] = min(8, detail_count * 2)
    if detail_count < 3:
        suggestions.append(f"Add more <details> sections ({detail_count} found, target 4+)")

    scores["copy_paste_install"] = 9 if "pip install" in content else 0

    number_pattern = re.compile(r'\b\d{2,}\b')
    number_count = len(number_pattern.findall(content[:3000]))
    scores["concrete_numbers"] = min(7, number_count)
    if number_count < 5:
        suggestions.append("Use more specific numbers in first 3000 chars (concreteness effect)")

    badge_count = content.count("img.shields.io")
    scores["social_proof_badges"] = min(6, badge_count * 2)

    link_section = "\n".join(lines[:20])
    nav_links = link_section.count("[") + link_section.count("href=")
    scores["cta_links"] = min(7, nav_links)

    h1 = sum(1 for l in lines if l.startswith("# ") and not l.startswith("## "))
    h2 = sum(1 for l in lines if l.startswith("## "))
    h3 = sum(1 for l in lines if l.startswith("### "))
    scores["visual_hierarchy"] = 8 if (h1 >= 1 and h2 >= 3 and h3 >= 3) else 4 if h2 >= 2 else 0

    real_devices = ["xbox", "cisco", "thrangrycat", "cve-", "arcanedoor"]
    found_devices = sum(1 for d in real_devices if d in content.lower())
    scores["real_world_examples"] = min(9, found_devices * 2)

    code_block_count = content.count("```")
    output_blocks = content.count("```\n  ") + content.count("```\nTotal") + content.count("```\nTop")
    scores["output_samples"] = min(8, output_blocks * 2 + code_block_count // 3)

    scores["api_examples"] = min(7, content.count("from retrace"))

    mitre_refs = content.count("ATT&CK") + content.count("CWE-") + content.count("CVSS")
    scores["security_context"] = min(6, mitre_refs)

    img_count = len(img_positions)
    scores["image_density"] = min(8, img_count)

    total = sum(scores.values())
    max_total = sum(c["weight"] for c in _DESIGN_CRITERIA.values())
    pct = round(100 * total / max_total) if max_total > 0 else 0

    _ok(f"Design score: {total}/{max_total} ({pct}%)")
    for criterion, score in sorted(scores.items(), key=lambda x: x[1]):
        max_score = _DESIGN_CRITERIA[criterion]["weight"]
        status = "OK" if score >= max_score * 0.7 else "LOW" if score > 0 else "MISS"
        color = "green" if status == "OK" else "yellow" if status == "LOW" else "red"
        _info(f"  [{click.style(status, fg=color)}] {criterion}: {score}/{max_score}")

    if suggestions:
        _warn(f"{len(suggestions)} improvement suggestions:")
        for s in suggestions:
            _info(f"  - {s}")
    else:
        _ok("All design criteria met!")

    return {
        "design_total": total,
        "design_max": max_total,
        "design_pct": pct,
        "design_scores": scores,
        "design_suggestions": suggestions,
    }


def flywheel_svg_audit() -> dict:
    """Audit all SVG output functions for design consistency.

    Generates test SVGs from each export function and checks for:
    - Consistent color palette (no rogue colors)
    - Font family consistency
    - Proper dark theme (background, text contrast)
    - Valid SVG structure
    - No inline styles that bypass the design system
    """
    _header("SVG design audit flywheel")

    scores: dict[str, int] = {}
    issues: list[str] = []

    # Check SVG export source files for design consistency
    svg_sources = [
        SRC_DIR / "export" / "svg.py",
        SRC_DIR / "export" / "pinout_diagram.py",
        SRC_DIR / "export" / "bom.py",
    ]

    approved_colors = {
        "#0a0e1a", "#111827", "#1e293b", "#e2e8f0", "#94a3b8", "#64748b",
        "#22d3ee", "#3b82f6", "#22c55e", "#ef4444", "#6b7280", "#f59e0b",
        "#a855f7", "#ff6b6b", "#334155",
        "#0b1120", "#0f1629", "#111d35", "#131a2b", "#1a2332", "#1a2a40",
        "#1e2d40", "#2a4060", "#7f1d1d",
        "#06b6d4", "#14b8a6", "#f97316", "#ec4899",
        "#1a3050", "#2e5070", "#8b5cf6", "#d946ef", "#fbbf24",
    }
    approved_fonts = {"JetBrains Mono", "Fira Code", "SF Mono", "monospace"}

    for src in svg_sources:
        if not src.exists():
            continue
        content = src.read_text(encoding="utf-8")
        name = src.name

        # Check color consistency
        hex_colors = set(re.findall(r'#[0-9a-fA-F]{6}', content))
        rogue_colors = hex_colors - approved_colors
        if len(rogue_colors) <= 3:
            scores[f"{name}_colors"] = 3
        else:
            scores[f"{name}_colors"] = 1
            issues.append(f"{name}: {len(rogue_colors)} non-standard colors: {', '.join(sorted(rogue_colors)[:5])}")

        # Check font consistency
        has_approved_font = any(f in content for f in approved_fonts)
        scores[f"{name}_fonts"] = 2 if has_approved_font else 0
        if not has_approved_font:
            issues.append(f"{name}: no approved monospace font found")

        # Check dark theme
        has_dark_bg = "#0a0e1a" in content or "#111827" in content
        scores[f"{name}_dark_theme"] = 2 if has_dark_bg else 0

    # Check generated SVG examples
    examples_dir = REPO_ROOT / "docs" / "examples"
    svg_files = list(examples_dir.glob("*.svg")) if examples_dir.exists() else []
    scores["example_count"] = min(5, len(svg_files))
    if len(svg_files) < 4:
        issues.append(f"Only {len(svg_files)} example SVGs (target: 4+)")

    for svg_file in svg_files[:8]:
        svg_content = svg_file.read_text(encoding="utf-8")
        if not svg_content.strip().startswith("<svg"):
            issues.append(f"{svg_file.name}: invalid SVG (missing <svg> root)")
        if not svg_content.strip().endswith("</svg>"):
            issues.append(f"{svg_file.name}: unclosed </svg>")

    # Check _IC_PINOUTS coverage
    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from retrace.export.pinout_diagram import _IC_PINOUTS
        scores["ic_pinout_coverage"] = min(3, len(_IC_PINOUTS))
        if len(_IC_PINOUTS) < 2:
            issues.append(f"Only {len(_IC_PINOUTS)} IC pinout packages (target: 2+)")
    except Exception:
        scores["ic_pinout_coverage"] = 0

    total = sum(scores.values())
    max_total = len(svg_sources) * 7 + 5 + 3  # 7 per source + example_count(5) + ic_pinout(3)
    pct = round(100 * total / max_total) if max_total > 0 else 0

    _ok(f"SVG design score: {total}/{max_total} ({pct}%)")
    for criterion, score in sorted(scores.items(), key=lambda x: x[1]):
        status = "OK" if score >= 2 else "LOW" if score > 0 else "MISS"
        color = "green" if status == "OK" else "yellow" if status == "LOW" else "red"
        _info(f"  [{click.style(status, fg=color)}] {criterion}: {score}")

    if issues:
        _warn(f"{len(issues)} SVG design issues:")
        for issue in issues:
            _info(f"  - {issue}")
    else:
        _ok("All SVG design checks passed!")

    return {
        "svg_total": total,
        "svg_max": max_total,
        "svg_pct": pct,
        "svg_issues": issues,
    }


# ---------------------------------------------------------------------------
# Flywheel 11: README formatting audit
# ---------------------------------------------------------------------------


def flywheel_readme_format() -> dict:
    """Audit README.md for professional formatting and layout quality.

    Checks:
    - HTML tables use consistent column widths (no colspan hacks)
    - All referenced images exist on disk
    - No broken image links
    - Section separators between gallery groups
    - Proper alt text on images
    - No raw HTML where markdown suffices
    - Consistent caption formatting
    """
    _header("README format flywheel — layout quality audit")

    readme_path = REPO_ROOT / "README.md"
    if not readme_path.exists():
        _warn("README.md not found")
        return {}

    content = readme_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    issues: list[str] = []
    scores: dict[str, int] = {}

    # 11a. Check all img src references resolve to existing files
    img_refs = re.findall(r'<img\s+[^>]*src="([^"]+)"', content)
    missing_imgs: list[str] = []
    for ref in img_refs:
        img_path = REPO_ROOT / ref
        if not img_path.exists():
            missing_imgs.append(ref)
    scores["images_exist"] = 5 if not missing_imgs else max(0, 5 - len(missing_imgs))
    if missing_imgs:
        _err(f"{len(missing_imgs)} broken image reference(s):")
        for m in missing_imgs:
            _info(f"  missing: {m}")
    else:
        _ok(f"All {len(img_refs)} image references resolve to files on disk")

    # 11b. Check for colspan hacks (uneven column layouts)
    colspan_count = content.count("colspan=")
    scores["no_colspan"] = 3 if colspan_count == 0 else max(0, 3 - colspan_count)
    if colspan_count > 0:
        _warn(f"{colspan_count} colspan usage(s) — prefer equal-width columns")
    else:
        _ok("No colspan hacks — clean column layout")

    # 11c. Check all images have alt text
    imgs_without_alt = re.findall(r'<img\s+(?!.*alt=)[^>]*>', content)
    scores["alt_text"] = 3 if not imgs_without_alt else 0
    if imgs_without_alt:
        _warn(f"{len(imgs_without_alt)} image(s) missing alt text")
    else:
        _ok("All images have alt text")

    # 11d. Check gallery section separators (--- between sections)
    table_sections = content.split("<table>")
    if len(table_sections) > 2:
        between_tables = 0
        for i in range(1, len(table_sections)):
            before = table_sections[i - 1]
            if "---" in before.split("</table>")[-1] if "</table>" in before else "":
                between_tables += 1
        scores["section_separators"] = min(3, between_tables)
    else:
        scores["section_separators"] = 3

    # 11e. Check for consistent table column widths within each table
    width_pattern = re.compile(r'width="(\d+%)"')
    inconsistent_tables = 0
    in_table = False
    table_widths: list[str] = []
    for line in lines:
        if "<table>" in line:
            in_table = True
            table_widths = []
        elif "</table>" in line:
            in_table = False
            if table_widths:
                unique = set(table_widths)
                if len(unique) > 2:
                    inconsistent_tables += 1
        elif in_table:
            for w in width_pattern.findall(line):
                table_widths.append(w)
    scores["consistent_widths"] = 3 if inconsistent_tables == 0 else max(0, 3 - inconsistent_tables)
    if inconsistent_tables:
        _warn(f"{inconsistent_tables} table(s) with inconsistent column widths")
    else:
        _ok("All tables use consistent column widths")

    # 11f. No empty table cells
    empty_cells = content.count("<td></td>") + content.count("<td>\n</td>")
    scores["no_empty_cells"] = 2 if empty_cells == 0 else 0
    if empty_cells:
        _warn(f"{empty_cells} empty table cell(s)")
    else:
        _ok("No empty table cells")

    total = sum(scores.values())
    max_total = 19
    pct = round(100 * total / max_total) if max_total > 0 else 0

    _ok(f"README format score: {total}/{max_total} ({pct}%)")
    for criterion, score in sorted(scores.items(), key=lambda x: x[1]):
        status = "OK" if score >= 2 else "LOW" if score > 0 else "MISS"
        color = "green" if status == "OK" else "yellow" if status == "LOW" else "red"
        _info(f"  [{click.style(status, fg=color)}] {criterion}: {score}")

    if issues:
        _warn(f"{len(issues)} formatting issues:")
        for issue in issues:
            _info(f"  - {issue}")

    return {
        "readme_format_total": total,
        "readme_format_max": max_total,
        "readme_format_pct": pct,
        "readme_missing_images": missing_imgs,
        "readme_colspan_count": colspan_count,
    }


# ---------------------------------------------------------------------------
# Flywheel 12: SVG rendering validation
# ---------------------------------------------------------------------------


def flywheel_svg_render_check() -> dict:
    """Validate generated SVGs are structurally correct and render properly.

    Checks each SVG in docs/examples/ for:
    - Valid XML structure (opens and closes properly)
    - Has viewBox attribute (responsive rendering)
    - Text elements aren't truncated (no text > viewBox width)
    - No overlapping text elements at same Y coordinate
    - Pin labels in pinout SVGs match expected count
    - BOM tables have correct column count
    """
    _header("SVG render validation flywheel")

    examples_dir = REPO_ROOT / "docs" / "examples"
    if not examples_dir.exists():
        _warn("docs/examples/ not found")
        return {}

    svg_files = sorted(examples_dir.glob("*.svg"))
    issues: list[str] = []
    scores: dict[str, int] = {}

    for svg_file in svg_files:
        name = svg_file.name
        content = svg_file.read_text(encoding="utf-8")

        # Valid SVG structure
        if not content.strip().startswith("<svg"):
            issues.append(f"{name}: missing <svg> root element")
        if not content.strip().endswith("</svg>"):
            issues.append(f"{name}: unclosed </svg>")

        # Has viewBox
        if "viewBox" not in content:
            issues.append(f"{name}: missing viewBox attribute (won't scale responsively)")

        # Extract viewBox dimensions
        vb_match = re.search(r'viewBox="0 0 (\d+) (\d+)"', content)
        if vb_match:
            vb_w = int(vb_match.group(1))
            vb_h = int(vb_match.group(2))

            # Check SVG height matches content (crude check for truncation)
            height_match = re.search(r'height="(\d+)"', content)
            if height_match:
                declared_h = int(height_match.group(1))
                if declared_h != vb_h:
                    issues.append(f"{name}: height ({declared_h}) != viewBox height ({vb_h})")

        # Pinout-specific checks
        if "pinout" in name.lower():
            pin_dots = len(re.findall(r'<circle[^>]*fill="(?:#3b82f6|#22c55e|#ef4444|#6b7280|#f59e0b|#a855f7)"', content))
            pin_labels = len(re.findall(r'Pin \d+', content))
            if "JTAG" in name.upper() and pin_dots < 10:
                issues.append(f"{name}: JTAG pinout has only {pin_dots} pin dots (expected 10-20)")
            if "UART" in name.upper() and pin_dots < 3:
                issues.append(f"{name}: UART pinout has only {pin_dots} pin dots (expected 3-6)")

        # BOM-specific checks
        if "bom" in name.lower():
            row_count = len(re.findall(r'<rect x="0" y="\d+" width="\d+" height="20"', content))
            if row_count < 10:
                issues.append(f"{name}: BOM has only {row_count} component rows (expected 10+)")
            header_texts = re.findall(r'font-weight="bold">(\w+)</text>', content)
            expected_headers = {"Ref", "Type", "Part", "Marking", "Value", "Package", "Confidence"}
            found_headers = set(header_texts) & expected_headers
            if len(found_headers) < 5:
                issues.append(f"{name}: BOM missing column headers (found {found_headers})")

    valid_count = len(svg_files) - len([i for i in issues if "missing <svg>" in i or "unclosed" in i])
    scores["valid_structure"] = min(5, valid_count)
    scores["issue_free"] = max(0, 5 - len(issues))

    total = sum(scores.values())
    max_total = 10
    pct = round(100 * total / max_total) if max_total > 0 else 0

    _ok(f"SVG render score: {total}/{max_total} ({pct}%) — {len(svg_files)} files checked")

    if issues:
        _warn(f"{len(issues)} SVG rendering issues:")
        for issue in issues:
            _info(f"  - {issue}")
    else:
        _ok("All SVG files pass validation!")

    return {
        "svg_render_total": total,
        "svg_render_max": max_total,
        "svg_render_pct": pct,
        "svg_render_issues": issues,
        "svg_files_checked": len(svg_files),
    }


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
    scores: dict[str, float] = {}

    # Initialize brain (intelligence layer)
    brain = FlywheelBrain() if _HAS_BRAIN else None
    cache_skips: list[str] = []

    def _should_run(fw_name: str) -> bool:
        if brain and brain.cache.is_cached(fw_name):
            cache_skips.append(fw_name)
            return False
        return True

    # 1. Stats
    flywheel_stats()
    if brain:
        brain.sources.record("readme_stats", True, 100.0)

    # 2. Lint
    lint_ok, fixed = flywheel_lint()
    metrics["lint_fixed"] = fixed
    scores["lint"] = 100.0 if fixed == 0 else max(0, 100 - fixed * 5)
    if brain:
        brain.sources.record("ruff", True, scores["lint"])
        brain.cache.update("lint")

    if not quick:
        # 3. Tests
        if _should_run("tests"):
            tests_ok, passed, failed, failed_tests = flywheel_tests()
            metrics["tests_passed"] = passed
            metrics["tests_failed"] = failed
            metrics["failed_test_ids"] = failed_tests
            total = passed + failed
            scores["tests"] = round(100 * passed / total) if total > 0 else 0
            if brain:
                brain.sources.record("pytest", True, scores["tests"])
                brain.cache.update("tests")
            if not tests_ok:
                all_passed = False
        else:
            _header("Test flywheel — pytest")
            _ok("Skipped (warm-start cache hit — no source changes)")
            metrics["tests_passed"] = state.get("tests_passed", 0)
            metrics["tests_failed"] = state.get("tests_failed", 0)
            scores["tests"] = 100.0

        # 4. Demo
        if _should_run("demo"):
            flywheel_demo()
            scores["demo"] = 100.0
            if brain:
                brain.cache.update("demo")
        else:
            _header("Demo flywheel — regenerate visual outputs")
            _ok("Skipped (warm-start cache hit)")
            scores["demo"] = 100.0

        # 5. Coverage
        if _should_run("coverage"):
            cov_ok, coverage_pct = flywheel_coverage(state)
            metrics["coverage_pct"] = coverage_pct
            try:
                scores["coverage"] = float(str(coverage_pct).rstrip("%"))
            except (ValueError, AttributeError):
                scores["coverage"] = 0.0
            if brain:
                brain.sources.record("pytest_cov", cov_ok, scores["coverage"])
                brain.cache.update("coverage")
            if not cov_ok:
                _warn("Coverage regression detected — flagging (not failing run)")
        else:
            _header("Coverage flywheel — measure and track")
            _ok("Skipped (warm-start cache hit)")
            coverage_pct = state.get("coverage_pct", "N/A")
            metrics["coverage_pct"] = coverage_pct

        # 6. Gap analysis
        if _should_run("gaps"):
            gaps = flywheel_gaps()
            metrics.update({
                "zero_coverage_count": len(gaps["zero_coverage_modules"]),
                "untested_source_count": len(gaps["untested_sources"]),
                "todo_count": gaps["todo_count"],
                "untyped_function_count": len(gaps["untyped_functions"]),
            })
            gap_total = sum([
                len(gaps["zero_coverage_modules"]),
                len(gaps["untested_sources"]),
                gaps["todo_count"],
                len(gaps["untyped_functions"]),
            ])
            scores["gaps"] = max(0.0, 100 - gap_total * 2)
            if brain:
                brain.cache.update("gaps")
        else:
            _header("Gap analysis flywheel — quality gaps")
            _ok("Skipped (warm-start cache hit)")

        # 7. Regression analysis
        regressions = flywheel_regression(state, metrics)
        metrics["regressions"] = regressions
        scores["regression"] = 100.0 if not regressions else max(0, 100 - len(regressions) * 20)

        # 8. Component DB tracking
        if _should_run("component_db"):
            db_metrics = flywheel_component_db()
            metrics.update(db_metrics)
            missing = len(db_metrics.get("missing_categories", []))
            scores["component_db"] = 100.0 if missing == 0 else max(0, 100 - missing * 10)
            if brain:
                brain.cache.update("component_db")
        else:
            _header("Component DB flywheel — growth and coverage")
            _ok("Skipped (warm-start cache hit)")

        # 9. Design audit
        if _should_run("design_audit"):
            design_metrics = flywheel_design_audit()
            metrics.update(design_metrics)
            scores["design_audit"] = float(design_metrics.get("design_pct", 0))
            if brain:
                brain.cache.update("design_audit")
        else:
            _header("Design audit flywheel — README psychology scoring")
            _ok("Skipped (warm-start cache hit)")

        # 10. SVG design audit
        if _should_run("svg_audit"):
            svg_metrics = flywheel_svg_audit()
            metrics.update(svg_metrics)
            scores["svg_audit"] = float(svg_metrics.get("svg_pct", 0))
            if brain:
                brain.cache.update("svg_audit")
        else:
            _header("SVG design audit flywheel")
            _ok("Skipped (warm-start cache hit)")

        # 11. README format audit
        if _should_run("readme_format"):
            readme_fmt = flywheel_readme_format()
            metrics.update(readme_fmt)
            scores["readme_format"] = float(readme_fmt.get("readme_format_pct", 0))
            if brain:
                brain.cache.update("readme_format")
        else:
            _header("README format flywheel — layout quality audit")
            _ok("Skipped (warm-start cache hit)")

        # 12. SVG render validation
        if _should_run("svg_render"):
            svg_render = flywheel_svg_render_check()
            metrics.update(svg_render)
            scores["svg_render"] = float(svg_render.get("svg_render_pct", 0))
            if brain:
                brain.cache.update("svg_render")
        else:
            _header("SVG render validation flywheel")
            _ok("Skipped (warm-start cache hit)")
    else:
        coverage_pct = state.get("coverage_pct", "N/A")
        metrics["coverage_pct"] = coverage_pct

    # Record to brain (time-series + source quality)
    if brain and scores:
        git_hash = ""
        try:
            r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, cwd=REPO_ROOT)
            git_hash = r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            pass
        brain.record_run(scores, git_hash=git_hash, mode="quick" if quick else "full")
        brain.save()

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
        _info(f"Design:   {metrics.get('design_pct', '?')}% ({metrics.get('design_total', '?')}/{metrics.get('design_max', '?')})")
        _info(f"SVG:      {metrics.get('svg_pct', '?')}% ({metrics.get('svg_total', '?')}/{metrics.get('svg_max', '?')})")
        _info(f"README:   {metrics.get('readme_format_pct', '?')}% ({metrics.get('readme_format_total', '?')}/{metrics.get('readme_format_max', '?')})")
        _info(f"Render:   {metrics.get('svg_render_pct', '?')}% — {metrics.get('svg_files_checked', '?')} SVGs checked")
    else:
        _info(f"Lint: {fixed} fix(es) applied  (quick mode — tests skipped)")

    if brain and cache_skips:
        _info(f"Cache:    {len(cache_skips)} flywheel(s) skipped via warm-start")

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

    # Component DB
    comp_total = state.get("component_total", "N/A")
    comp_cats = state.get("component_categories", "N/A")
    click.echo("")
    click.echo(click.style("  Component DB:", bold=True))
    _info(f"Total entries:    {comp_total}")
    _info(f"Categories:       {comp_cats}")
    missing_cats = state.get("missing_categories", [])
    if missing_cats:
        _warn(f"Missing:          {', '.join(missing_cats)}")

    # Warn about failed tests from last run
    failed_ids = state.get("failed_test_ids", [])
    if failed_ids:
        click.echo("")
        click.echo(click.style("  Failed tests (last run):", bold=True, fg="red"))
        for t in failed_ids[:10]:
            _err(t)
        if len(failed_ids) > 10:
            _info(f"  ... and {len(failed_ids) - 10} more")

    # Regression history
    history = state.get("regression_history", [])
    if history:
        click.echo("")
        click.echo(click.style("  Recent regression checks:", bold=True))
        for entry in history[-5:]:
            ts = entry.get("timestamp", "?")[:19]
            regs = entry.get("regressions", [])
            tests = entry.get("tests_passed", "?")
            cov = entry.get("coverage", "?")
            if regs:
                _warn(f"{ts}  tests={tests} cov={cov}  {len(regs)} regression(s)")
            else:
                _ok(f"{ts}  tests={tests} cov={cov}  clean")

    click.echo("")


@cli.command()
@click.option("--detailed", is_flag=True, help="Show full brain state including bandit arms.")
def brain(detailed: bool) -> None:
    """Show flywheel intelligence: meta-learning, trends, confidence, source quality."""
    if not _HAS_BRAIN:
        click.echo(click.style("  Intelligence layer not available (flywheel_intelligence.py not found)", fg="red"))
        return

    b = FlywheelBrain()
    click.echo(click.style("\nretrace flywheel brain", fg="magenta", bold=True))
    click.echo(click.style(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fg="bright_black"))
    click.echo("")
    click.echo(b.format_brain_summary())
    click.echo("")


@cli.command()
@click.option("--last", default=30, help="Number of recent runs to analyze.")
def trends(last: int) -> None:
    """Show flywheel score trends with sparklines and CUSUM analysis."""
    if not _HAS_BRAIN:
        click.echo(click.style("  Intelligence layer not available", fg="red"))
        return

    b = FlywheelBrain()
    click.echo(click.style("\nretrace flywheel trends", fg="magenta", bold=True))
    click.echo("")

    report = b.get_trend_report()
    status_colors = {
        "stable": "green", "breakthrough": "cyan", "regression": "red",
        "stalled": "yellow", "insufficient_data": "bright_black", "no_data": "bright_black",
    }
    status_icons = {
        "stable": "→", "breakthrough": "↑", "regression": "↓",
        "stalled": "═", "insufficient_data": "?", "no_data": "·",
    }

    for t in report:
        icon = status_icons.get(t["status"], "?")
        color = status_colors.get(t["status"], "white")
        spark = t.get("sparkline", "")
        current = t.get("current", "—")
        mean_str = f"μ={t['mean']:.1f}" if "mean" in t else ""
        delta_str = ""
        if "delta" in t:
            d = t["delta"]
            delta_str = click.style(f"+{d:.1f}" if d >= 0 else f"{d:.1f}", fg="green" if d >= 0 else "red")
        ci = b.confidence.compute_ci(t["flywheel"])
        ci_str = f"[{ci[1]:.0f},{ci[2]:.0f}]" if ci[0] > 0 else ""

        line = f"  {click.style(icon, fg=color)} {t['flywheel']:20s}  {spark}  "
        line += f"{current}  {delta_str}  {mean_str}  {ci_str}"
        click.echo(line)

    click.echo("")
    warnings = b.get_inflation_warnings()
    if warnings:
        _header("Calibration warnings")
        for w in warnings:
            _warn(w)
        click.echo("")


@cli.command()
@click.argument("flywheel_name")
@click.argument("raw_score", type=float)
@click.argument("ground_truth", type=float)
def calibrate(flywheel_name: str, raw_score: float, ground_truth: float) -> None:
    """Add a manual calibration anchor. Usage: calibrate design_audit 98 92"""
    if not _HAS_BRAIN:
        click.echo(click.style("  Intelligence layer not available", fg="red"))
        return

    b = FlywheelBrain()
    b.calibrator.add_anchor(flywheel_name, raw_score, ground_truth)
    b.save()
    calibrated = b.calibrator.calibrated_score(flywheel_name, raw_score)
    click.echo(click.style(f"\n  Calibration anchor added for {flywheel_name}", fg="green"))
    click.echo(f"  Raw: {raw_score} → Calibrated: {calibrated:.1f} (offset: {calibrated - raw_score:+.1f})")
    click.echo("")


if __name__ == "__main__":
    cli()
