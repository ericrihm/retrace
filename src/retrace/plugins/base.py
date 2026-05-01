"""Plugin protocol and discovery for the retrace analyzer plugin system."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class AnalyzerPlugin(Protocol):
    """Protocol that all retrace analyzer plugins must satisfy.

    Plugins are discovered via the ``retrace.plugins`` entry-point group.
    Each plugin is a class with:
      - a ``name`` class attribute (str)
      - an ``analyze(board)`` method that accepts an AnalysisResult and
        returns a dict of findings.

    Example entry_points configuration in pyproject.toml::

        [project.entry-points."retrace.plugins"]
        my_plugin = "mypackage.myplugin:MyPlugin"
    """

    name: str

    def analyze(self, board: Any) -> dict[str, Any]:
        """Run this plugin against a board analysis result.

        Args:
            board: An :class:`retrace.core.pipeline.AnalysisResult` instance.

        Returns:
            A dict with at minimum a ``"findings"`` key containing a list of
            finding dicts, each with ``"type"``, ``"severity"``, and
            ``"description"`` keys.
        """
        ...


def discover_plugins() -> list[type]:
    """Discover installed retrace plugins via setuptools entry points.

    Looks for the ``retrace.plugins`` entry-point group and attempts to load
    each registered class. Failed loads are logged and skipped.

    Returns:
        List of plugin classes that satisfy the :class:`AnalyzerPlugin` protocol.
    """
    plugins: list[type] = []
    try:
        eps = importlib.metadata.entry_points(group="retrace.plugins")
    except Exception as exc:
        logger.debug(f"Entry point discovery failed: {exc}")
        return plugins

    for ep in eps:
        try:
            cls = ep.load()
            if isinstance(cls, type):
                plugins.append(cls)
                logger.debug(f"Loaded plugin: {ep.name} -> {cls}")
            else:
                logger.warning(f"Plugin {ep.name} does not satisfy AnalyzerPlugin protocol")
        except Exception as exc:
            logger.warning(f"Failed to load plugin {ep.name}: {exc}")

    return plugins


def run_plugins(board: Any, plugin_classes: list[type] | None = None) -> list[dict[str, Any]]:
    """Run all discovered (or provided) plugins against a board result.

    Args:
        board: An AnalysisResult instance to analyse.
        plugin_classes: Explicit list of plugin classes to run. When None,
            calls :func:`discover_plugins` to find installed plugins.

    Returns:
        List of finding dicts, aggregated from all plugins.
    """
    if plugin_classes is None:
        plugin_classes = discover_plugins()

    all_findings: list[dict[str, Any]] = []
    for cls in plugin_classes:
        try:
            instance = cls()
            result = instance.analyze(board)
            findings = result.get("findings", [])
            for f in findings:
                f.setdefault("plugin", getattr(cls, "name", cls.__name__))
            all_findings.extend(findings)
        except Exception as exc:
            logger.warning(f"Plugin {cls} raised during analyze(): {exc}")

    return all_findings
