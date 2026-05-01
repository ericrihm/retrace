"""Test that python -m retrace invokes the CLI."""

from unittest.mock import patch


def test_main_invokes_cli():
    with patch("retrace.cli.main") as mock_main:
        mock_main.return_value = None
        import retrace.__main__  # noqa: F401
        mock_main.assert_called()
