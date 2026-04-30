"""Tests for retrace.web — Gradio web UI stub."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_demo_mock():
    """Create a minimal Gradio demo mock usable as a context manager."""
    demo = MagicMock()
    demo.__enter__ = MagicMock(return_value=demo)
    demo.__exit__ = MagicMock(return_value=False)
    return demo


def _make_gr_mock(demo=None):
    """Build a minimal Gradio module mock."""
    if demo is None:
        demo = _make_demo_mock()
    gr = MagicMock()
    gr.Blocks.return_value = demo
    return gr, demo


def _launch_with_gr_mock(share=False, port=7860, btn_click_spy=None):
    """
    Call web.launch() with a fully mocked gradio module.

    Returns (demo_mock, call_args) so callers can assert on demo.launch calls.
    Uses patch.dict only on 'gradio' and ensures pipeline stays in sys.modules
    to avoid the numpy-can't-reload-twice problem on Python 3.14.
    """
    import sys
    import retrace.core.pipeline  # noqa: F401 — ensure cached before patch.dict removes it

    gr, demo = _make_gr_mock()

    if btn_click_spy is not None:
        btn_mock = MagicMock()
        btn_mock.click = btn_click_spy
        gr.Button.return_value = btn_mock

    # Keep pipeline in the patched sys.modules so it is NOT re-imported inside
    # the with-block (which would cause numpy to be loaded a second time).
    pipeline_mod = sys.modules["retrace.core.pipeline"]

    with patch.dict(
        "sys.modules",
        {"gradio": gr, "retrace.core.pipeline": pipeline_mod},
    ):
        import retrace.web as web_mod
        web_mod.launch(share=share, port=port)

    return demo


# ---------------------------------------------------------------------------
# launch() signature / defaults — no import side-effects
# ---------------------------------------------------------------------------

def test_launch_default_signature():
    """launch() should accept share and port keyword arguments with correct defaults."""
    import inspect
    from retrace.web import launch

    sig = inspect.signature(launch)
    params = sig.parameters
    assert "share" in params
    assert "port" in params
    assert params["share"].default is False
    assert params["port"].default == 7860


def test_launch_returns_none_annotation():
    """launch() must be annotated -> None (string form due to __future__ annotations)."""
    import inspect
    from retrace.web import launch

    sig = inspect.signature(launch)
    ann = sig.return_annotation
    assert ann is None or ann == "None", f"Expected None annotation, got {ann!r}"


# ---------------------------------------------------------------------------
# launch() without Gradio — patch the import inside launch()
# ---------------------------------------------------------------------------

def test_launch_no_gradio_prints_message(capsys):
    """When gradio is not installed, launch() prints an install hint and returns None."""
    import builtins
    real_import = builtins.__import__

    def import_blocker(name, *args, **kwargs):
        if name == "gradio":
            raise ImportError("gradio not installed")
        return real_import(name, *args, **kwargs)

    from retrace.web import launch

    with patch("builtins.__import__", side_effect=import_blocker):
        result = launch()

    captured = capsys.readouterr()
    assert result is None
    assert "gradio" in captured.out.lower() or "pip install" in captured.out.lower()


def test_launch_no_gradio_returns_none():
    """launch() must return None when gradio is absent."""
    import builtins
    real_import = builtins.__import__

    def import_blocker(name, *args, **kwargs):
        if name == "gradio":
            raise ImportError("gradio not installed")
        return real_import(name, *args, **kwargs)

    from retrace.web import launch

    with patch("builtins.__import__", side_effect=import_blocker):
        result = launch()

    assert result is None


# ---------------------------------------------------------------------------
# launch() with Gradio mocked
# ---------------------------------------------------------------------------

def test_launch_with_gradio_calls_demo_launch():
    """When gradio is available, launch() should call demo.launch()."""
    demo = _launch_with_gr_mock()
    demo.launch.assert_called_once()


def test_launch_with_gradio_passes_share_false():
    """share=False should be forwarded to demo.launch()."""
    demo = _launch_with_gr_mock(share=False)
    demo.launch.assert_called_once()
    call_kwargs = demo.launch.call_args
    all_positional = list(call_kwargs.args)
    kw = call_kwargs.kwargs
    assert False in all_positional or kw.get("share") is False


def test_launch_with_gradio_passes_custom_port():
    """Custom port should be forwarded to demo.launch()."""
    demo = _launch_with_gr_mock(port=8080)
    demo.launch.assert_called_once()
    call_kwargs = demo.launch.call_args
    all_positional = list(call_kwargs.args)
    kw = call_kwargs.kwargs
    assert 8080 in all_positional or kw.get("server_port") == 8080


# ---------------------------------------------------------------------------
# _scan internal helper — test through btn.click registration
# ---------------------------------------------------------------------------

def test_scan_helper_none_image():
    """_scan(None) should return a 3-tuple with a non-empty string as first element."""
    import sys
    import retrace.core.pipeline  # noqa: F401 — ensure cached

    gr, demo = _make_gr_mock()
    captured_scan: dict = {}

    btn_mock = MagicMock()

    def fake_click(fn, inputs, outputs):
        captured_scan["fn"] = fn

    btn_mock.click = fake_click
    gr.Button.return_value = btn_mock

    pipeline_mod = sys.modules["retrace.core.pipeline"]

    with patch.dict(
        "sys.modules",
        {"gradio": gr, "retrace.core.pipeline": pipeline_mod},
    ):
        import retrace.web as web_mod
        web_mod.launch()

    assert "fn" in captured_scan, "_scan was never registered via btn.click"
    _scan = captured_scan["fn"]

    result = _scan(None)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 3
    assert isinstance(result[0], str) and result[0], "First element must be a non-empty string"


# ---------------------------------------------------------------------------
# Integration test — runs only when gradio is actually installed
# ---------------------------------------------------------------------------

def test_launch_with_real_gradio_if_available():
    """If gradio is importable, launch() should complete without raising."""
    pytest.importorskip("gradio")
    from retrace.web import launch

    with patch("gradio.Blocks") as mock_blocks:
        demo = _make_demo_mock()
        mock_blocks.return_value = demo
        launch(share=False, port=7861)

    demo.launch.assert_called_once()
