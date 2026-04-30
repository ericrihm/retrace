"""Configuration management for re:trace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "retrace"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "retrace"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "retrace"


@dataclass
class RetraceConfig:
    config_dir: Path = DEFAULT_CONFIG_DIR
    cache_dir: Path = DEFAULT_CACHE_DIR
    data_dir: Path = DEFAULT_DATA_DIR
    model_path: str = ""
    ocr_engine: str = "easyocr"
    detection_confidence: float = 0.25
    trace_min_length: int = 20
    enable_learning: bool = True
    octopart_api_key: str = ""

    def ensure_dirs(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
