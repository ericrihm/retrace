"""Tests for src/retrace/core/config.py — no ML dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from retrace.core.config import (
    DEFAULT_CACHE_DIR,
    DEFAULT_CONFIG_DIR,
    DEFAULT_DATA_DIR,
    RetraceConfig,
)

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_config_dir(self):
        cfg = RetraceConfig()
        assert cfg.config_dir == DEFAULT_CONFIG_DIR

    def test_default_cache_dir(self):
        cfg = RetraceConfig()
        assert cfg.cache_dir == DEFAULT_CACHE_DIR

    def test_default_data_dir(self):
        cfg = RetraceConfig()
        assert cfg.data_dir == DEFAULT_DATA_DIR

    def test_default_config_dir_path_type(self):
        cfg = RetraceConfig()
        assert isinstance(cfg.config_dir, Path)

    def test_default_cache_dir_path_type(self):
        cfg = RetraceConfig()
        assert isinstance(cfg.cache_dir, Path)

    def test_default_data_dir_path_type(self):
        cfg = RetraceConfig()
        assert isinstance(cfg.data_dir, Path)

    def test_default_model_path_empty(self):
        cfg = RetraceConfig()
        assert cfg.model_path == ""

    def test_default_ocr_engine(self):
        cfg = RetraceConfig()
        assert cfg.ocr_engine == "easyocr"

    def test_default_detection_confidence(self):
        cfg = RetraceConfig()
        assert cfg.detection_confidence == pytest.approx(0.25)

    def test_default_trace_min_length(self):
        cfg = RetraceConfig()
        assert cfg.trace_min_length == 20

    def test_default_enable_learning(self):
        cfg = RetraceConfig()
        assert cfg.enable_learning is True

    def test_default_octopart_api_key_empty(self):
        cfg = RetraceConfig()
        assert cfg.octopart_api_key == ""

    def test_default_dirs_under_home(self):
        home = Path.home()
        cfg = RetraceConfig()
        assert cfg.config_dir.is_relative_to(home)
        assert cfg.cache_dir.is_relative_to(home)
        assert cfg.data_dir.is_relative_to(home)

    def test_default_config_subpath(self):
        """Default paths should include 'retrace' somewhere in them."""
        cfg = RetraceConfig()
        assert "retrace" in str(cfg.config_dir)
        assert "retrace" in str(cfg.cache_dir)
        assert "retrace" in str(cfg.data_dir)


# ---------------------------------------------------------------------------
# ensure_dirs creates directories
# ---------------------------------------------------------------------------

class TestEnsureDirs:
    def test_ensure_dirs_creates_config_dir(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "config",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        assert cfg.config_dir.exists()

    def test_ensure_dirs_creates_cache_dir(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "config",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        assert cfg.cache_dir.exists()

    def test_ensure_dirs_creates_data_dir(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "config",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        assert cfg.data_dir.exists()

    def test_ensure_dirs_creates_nested_paths(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "a" / "b" / "config",
            cache_dir=tmp_path / "c" / "d" / "cache",
            data_dir=tmp_path / "e" / "f" / "data",
        )
        cfg.ensure_dirs()
        assert cfg.config_dir.is_dir()
        assert cfg.cache_dir.is_dir()
        assert cfg.data_dir.is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path: Path):
        """Calling ensure_dirs twice must not raise."""
        cfg = RetraceConfig(
            config_dir=tmp_path / "config",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        cfg.ensure_dirs()  # Second call should not raise
        assert cfg.config_dir.exists()

    def test_ensure_dirs_already_exist(self, tmp_path: Path):
        """Pre-created directories should not cause errors."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        cfg = RetraceConfig(
            config_dir=config_dir,
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        assert config_dir.is_dir()

    def test_ensure_dirs_dirs_are_directories_not_files(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "config",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )
        cfg.ensure_dirs()
        assert cfg.config_dir.is_dir()
        assert cfg.cache_dir.is_dir()
        assert cfg.data_dir.is_dir()


# ---------------------------------------------------------------------------
# Custom paths
# ---------------------------------------------------------------------------

class TestCustomPaths:
    def test_custom_config_dir(self, tmp_path: Path):
        custom = tmp_path / "my_config"
        cfg = RetraceConfig(config_dir=custom)
        assert cfg.config_dir == custom

    def test_custom_cache_dir(self, tmp_path: Path):
        custom = tmp_path / "my_cache"
        cfg = RetraceConfig(cache_dir=custom)
        assert cfg.cache_dir == custom

    def test_custom_data_dir(self, tmp_path: Path):
        custom = tmp_path / "my_data"
        cfg = RetraceConfig(data_dir=custom)
        assert cfg.data_dir == custom

    def test_custom_model_path(self):
        cfg = RetraceConfig(model_path="/models/yolo.pt")
        assert cfg.model_path == "/models/yolo.pt"

    def test_custom_ocr_engine(self):
        cfg = RetraceConfig(ocr_engine="tesseract")
        assert cfg.ocr_engine == "tesseract"

    def test_custom_detection_confidence(self):
        cfg = RetraceConfig(detection_confidence=0.75)
        assert cfg.detection_confidence == pytest.approx(0.75)

    def test_custom_trace_min_length(self):
        cfg = RetraceConfig(trace_min_length=50)
        assert cfg.trace_min_length == 50

    def test_disable_learning(self):
        cfg = RetraceConfig(enable_learning=False)
        assert cfg.enable_learning is False

    def test_custom_octopart_api_key(self):
        cfg = RetraceConfig(octopart_api_key="abc123")
        assert cfg.octopart_api_key == "abc123"

    def test_custom_dirs_ensure_dirs(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "custom_cfg",
            cache_dir=tmp_path / "custom_cache",
            data_dir=tmp_path / "custom_data",
        )
        cfg.ensure_dirs()
        assert (tmp_path / "custom_cfg").is_dir()
        assert (tmp_path / "custom_cache").is_dir()
        assert (tmp_path / "custom_data").is_dir()

    def test_all_custom_combined(self, tmp_path: Path):
        cfg = RetraceConfig(
            config_dir=tmp_path / "cfg",
            cache_dir=tmp_path / "cch",
            data_dir=tmp_path / "dat",
            model_path="/some/model.pt",
            ocr_engine="tesseract",
            detection_confidence=0.9,
            trace_min_length=10,
            enable_learning=False,
            octopart_api_key="key-xyz",
        )
        assert cfg.model_path == "/some/model.pt"
        assert cfg.ocr_engine == "tesseract"
        assert cfg.detection_confidence == pytest.approx(0.9)
        assert cfg.trace_min_length == 10
        assert cfg.enable_learning is False
        assert cfg.octopart_api_key == "key-xyz"

    def test_config_is_dataclass_mutable(self, tmp_path: Path):
        cfg = RetraceConfig()
        cfg.config_dir = tmp_path / "new_cfg"
        assert cfg.config_dir == tmp_path / "new_cfg"
