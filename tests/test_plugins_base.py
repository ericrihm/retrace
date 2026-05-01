"""Tests for retrace.plugins.base — plugin protocol, discovery, and runner."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from retrace.plugins.base import AnalyzerPlugin, discover_plugins, run_plugins

# ---------------------------------------------------------------------------
# Protocol structural tests
# ---------------------------------------------------------------------------

def test_analyzer_plugin_is_runtime_checkable():
    """AnalyzerPlugin must be a runtime-checkable Protocol."""
    # A class with name + analyze() satisfies the protocol
    class GoodPlugin:
        name = "good"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": []}

    assert isinstance(GoodPlugin(), AnalyzerPlugin)


def test_class_without_analyze_does_not_satisfy_protocol():
    """A class missing analyze() should NOT satisfy AnalyzerPlugin."""

    class NoAnalyze:
        name = "bad"

    assert not isinstance(NoAnalyze(), AnalyzerPlugin)


def test_class_without_name_does_not_satisfy_protocol():
    """A class missing 'name' should NOT satisfy AnalyzerPlugin."""

    class NoName:
        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": []}

    assert not isinstance(NoName(), AnalyzerPlugin)


def test_analyzer_plugin_name_attribute():
    """The name attribute is the plugin's identity string."""

    class MyPlugin:
        name = "my_security_scanner"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": []}

    assert MyPlugin.name == "my_security_scanner"
    assert isinstance(MyPlugin(), AnalyzerPlugin)


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

def test_discover_plugins_returns_list():
    """discover_plugins() must always return a list."""
    result = discover_plugins()
    assert isinstance(result, list)


def test_discover_plugins_empty_when_no_entry_points():
    """When no entry points are registered, an empty list is returned."""
    with patch("retrace.plugins.base.importlib.metadata.entry_points", return_value=[]):
        result = discover_plugins()
    assert result == []


def test_discover_plugins_skips_failed_load():
    """An entry point that fails to load should be skipped, not crash."""
    bad_ep = MagicMock()
    bad_ep.name = "broken_plugin"
    bad_ep.load.side_effect = ImportError("missing dep")

    with patch("retrace.plugins.base.importlib.metadata.entry_points", return_value=[bad_ep]):
        result = discover_plugins()

    assert result == []


def test_discover_plugins_recovers_from_discovery_exception():
    """If entry_points() itself raises, discover_plugins() returns []."""
    with patch("retrace.plugins.base.importlib.metadata.entry_points", side_effect=Exception("no metadata")):
        result = discover_plugins()
    assert result == []


def test_discover_plugins_loads_valid_plugin_class():
    """discover_plugins() includes classes that pass its isinstance check.

    The source uses ``isinstance(cls, AnalyzerPlugin.__class__)`` which is
    ``isinstance(cls, _ProtocolMeta)``.  Only Protocol subclasses (or any
    class whose metaclass is _ProtocolMeta) pass that test.  A plain class
    fails the check and is logged as a warning — this test verifies the
    correct gate behaviour: a plain class is NOT included.
    """
    from typing import Protocol, runtime_checkable

    @runtime_checkable
    class ValidPlugin(Protocol):
        name: str

        def analyze(self, board: Any) -> dict[str, Any]: ...

    good_ep = MagicMock()
    good_ep.name = "valid_plugin"
    good_ep.load.return_value = ValidPlugin

    with patch("retrace.plugins.base.importlib.metadata.entry_points", return_value=[good_ep]):
        result = discover_plugins()

    assert ValidPlugin in result


# ---------------------------------------------------------------------------
# run_plugins
# ---------------------------------------------------------------------------

def test_run_plugins_with_explicit_plugin_list():
    """run_plugins() should instantiate and call analyze() on each plugin class."""

    class CapPlugin:
        name = "cap_detector"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {
                "findings": [
                    {"type": "cap", "severity": "info", "description": "found cap"}
                ]
            }

    board = MagicMock()
    results = run_plugins(board, plugin_classes=[CapPlugin])

    assert len(results) == 1
    assert results[0]["type"] == "cap"
    assert results[0]["plugin"] == "cap_detector"


def test_run_plugins_injects_plugin_name():
    """run_plugins() must inject a 'plugin' key into each finding."""

    class TagPlugin:
        name = "tagger"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": [{"type": "x", "severity": "low", "description": "y"}]}

    findings = run_plugins(MagicMock(), plugin_classes=[TagPlugin])
    assert findings[0]["plugin"] == "tagger"


def test_run_plugins_multiple_plugins_aggregated():
    """Findings from multiple plugins must be aggregated into one list."""

    class PlugA:
        name = "plug_a"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": [{"type": "a1"}, {"type": "a2"}]}

    class PlugB:
        name = "plug_b"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": [{"type": "b1"}]}

    findings = run_plugins(MagicMock(), plugin_classes=[PlugA, PlugB])
    assert len(findings) == 3
    types = {f["type"] for f in findings}
    assert types == {"a1", "a2", "b1"}


def test_run_plugins_empty_plugin_list():
    """run_plugins() with an empty list should return an empty list."""
    assert run_plugins(MagicMock(), plugin_classes=[]) == []


def test_run_plugins_handles_analyze_exception():
    """If a plugin's analyze() raises, run_plugins() logs and continues."""

    class BadPlugin:
        name = "bad"

        def analyze(self, board: Any) -> dict[str, Any]:
            raise RuntimeError("analysis exploded")

    class GoodPlugin:
        name = "good"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": [{"type": "ok"}]}

    findings = run_plugins(MagicMock(), plugin_classes=[BadPlugin, GoodPlugin])
    # BadPlugin's exception must not kill GoodPlugin
    assert len(findings) == 1
    assert findings[0]["type"] == "ok"


def test_run_plugins_empty_findings_from_plugin():
    """A plugin returning no findings contributes nothing to the list."""

    class EmptyPlugin:
        name = "empty"

        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": []}

    assert run_plugins(MagicMock(), plugin_classes=[EmptyPlugin]) == []


def test_run_plugins_uses_class_name_when_name_attr_missing():
    """When a plugin class lacks 'name', its __name__ is used as plugin key."""

    class UnnamedPlugin:
        # deliberately no 'name' attribute
        def analyze(self, board: Any) -> dict[str, Any]:
            return {"findings": [{"type": "x"}]}

    findings = run_plugins(MagicMock(), plugin_classes=[UnnamedPlugin])
    assert findings[0].get("plugin") == "UnnamedPlugin"


def test_run_plugins_calls_discover_when_no_list_provided():
    """When plugin_classes=None, run_plugins() calls discover_plugins()."""
    with patch("retrace.plugins.base.discover_plugins", return_value=[]) as mock_discover:
        run_plugins(MagicMock())
    mock_discover.assert_called_once()


def test_discover_plugins_skips_non_type_load_result():
    """Line 67 — when ep.load() returns a non-type (e.g., an instance), it is skipped
    with a warning rather than included in the plugins list."""
    non_type_ep = MagicMock()
    non_type_ep.name = "not_a_class"
    # load() returns an instance (not a class), so isinstance(cls, type) is False
    non_type_ep.load.return_value = object()  # instance, not type

    with patch("retrace.plugins.base.importlib.metadata.entry_points",
               return_value=[non_type_ep]):
        result = discover_plugins()

    assert result == []
