"""Main analysis pipeline — photo in, structured analysis out."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Component:
    id: str
    label: str  # ic, capacitor, resistor, connector, inductor, crystal, header, test_point
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, w, h
    marking: str = ""
    part_number: str = ""
    datasheet_url: str = ""
    value: str = ""
    package: str = ""


@dataclass
class Trace:
    id: str
    points: list[tuple[int, int]]
    width_px: float = 0.0
    from_component: str = ""
    to_component: str = ""


@dataclass
class AnalysisResult:
    image_path: str
    components: list[Component] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    board_dimensions: tuple[int, int] = (0, 0)
    layer_count_estimate: int = 0
    duration_seconds: float = 0.0
    pipeline_version: str = "0.1.0"
    timestamp: str = ""

    def summary(self) -> dict:
        by_label = {}
        for c in self.components:
            by_label[c.label] = by_label.get(c.label, 0) + 1
        return {
            "image": self.image_path,
            "components": len(self.components),
            "components_by_type": by_label,
            "traces": len(self.traces),
            "identified": sum(1 for c in self.components if c.part_number),
            "duration_seconds": round(self.duration_seconds, 2),
        }

    def save(self, output_dir: Path, fmt: str = "json"):
        output_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            data = {
                "version": self.pipeline_version,
                "timestamp": self.timestamp,
                "image": self.image_path,
                "components": [asdict(c) for c in self.components],
                "traces": [asdict(t) for t in self.traces],
                "summary": self.summary(),
            }
            (output_dir / "analysis.json").write_text(json.dumps(data, indent=2) + "\n")

        elif fmt == "csv":
            lines = ["id,label,confidence,marking,part_number,value,package"]
            for c in self.components:
                lines.append(
                    f"{c.id},{c.label},{c.confidence:.3f},"
                    f"{c.marking},{c.part_number},{c.value},{c.package}"
                )
            (output_dir / "components.csv").write_text("\n".join(lines) + "\n")


class Pipeline:
    """Orchestrates the full PCB analysis pipeline."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._detector = None
        self._ocr = None
        self._trace_extractor = None

    def run(self, image_path: str) -> AnalysisResult:
        start = time.time()
        logger.info(f"Analyzing: {image_path}")

        img = self._load_image(image_path)
        h, w = img.shape[:2]

        result = AnalysisResult(
            image_path=image_path,
            board_dimensions=(w, h),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        # Phase 1: Component detection
        logger.info("Phase 1: Detecting components...")
        result.components = self._detect_components(img)
        logger.info(f"  Found {len(result.components)} components")

        # Phase 2: OCR chip markings
        logger.info("Phase 2: Reading chip markings...")
        result.components = self._read_markings(img, result.components)
        identified = sum(1 for c in result.components if c.marking)
        logger.info(f"  Read {identified} markings")

        # Phase 3: Trace extraction
        logger.info("Phase 3: Extracting traces...")
        result.traces = self._extract_traces(img)
        logger.info(f"  Found {len(result.traces)} traces")

        # Phase 4: Component identification
        logger.info("Phase 4: Identifying components...")
        result.components = self._identify_components(result.components)
        identified = sum(1 for c in result.components if c.part_number)
        logger.info(f"  Identified {identified} components")

        result.duration_seconds = time.time() - start
        logger.info(f"Analysis complete in {result.duration_seconds:.1f}s")
        return result

    def _load_image(self, path: str) -> np.ndarray:
        try:
            import cv2
            img = cv2.imread(path)
            if img is None:
                raise ValueError(f"Could not load image: {path}")
            return img
        except ImportError:
            from PIL import Image
            img = Image.open(path)
            return np.array(img)

    def _detect_components(self, img: np.ndarray) -> list[Component]:
        try:
            from retrace.detection.detector import YOLODetector
            if self._detector is None:
                self._detector = YOLODetector()
            return self._detector.detect(img)
        except ImportError:
            logger.warning("YOLO not available — using contour-based fallback")
            return self._detect_contours(img)

    def _detect_contours(self, img: np.ndarray) -> list[Component]:
        """Fallback: OpenCV contour-based component detection."""
        try:
            import cv2
        except ImportError:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        components = []
        min_area = (img.shape[0] * img.shape[1]) * 0.001
        max_area = (img.shape[0] * img.shape[1]) * 0.15

        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect = w / max(h, 1)

                if aspect > 2.5 or aspect < 0.4:
                    label = "connector"
                elif area > max_area * 0.3:
                    label = "ic"
                elif 0.8 < aspect < 1.2 and area < min_area * 10:
                    label = "capacitor"
                else:
                    label = "resistor"

                components.append(Component(
                    id=f"C{i:04d}",
                    label=label,
                    confidence=0.5,
                    bbox=(x, y, w, h),
                ))

        return components

    def _read_markings(self, img: np.ndarray, components: list[Component]) -> list[Component]:
        try:
            from retrace.detection.ocr import read_markings
            return read_markings(img, components)
        except ImportError:
            return components

    def _extract_traces(self, img: np.ndarray) -> list[Trace]:
        try:
            from retrace.detection.trace_extractor import extract_traces_from_image
            return extract_traces_from_image(img)
        except ImportError:
            return []

    def _identify_components(self, components: list[Component]) -> list[Component]:
        try:
            from retrace.identification.matcher import identify_components
            return identify_components(components)
        except ImportError:
            return components
