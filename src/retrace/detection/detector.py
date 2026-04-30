"""YOLO v8 PCB component detector.

Wraps Ultralytics YOLOv8 to detect electronic components (ICs, capacitors,
resistors, connectors, etc.) in board photos.  Falls back gracefully when
the ``ultralytics`` package is not installed.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from retrace.core.pipeline import Component

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label mapping from YOLO class index → Component.label string
# ---------------------------------------------------------------------------
_LABEL_MAP: dict[int, str] = {
    0: "ic",
    1: "capacitor",
    2: "resistor",
    3: "connector",
    4: "inductor",
    5: "crystal",
    6: "header",
    7: "test_point",
    8: "diode",
    9: "transistor",
}

_DEFAULT_MODEL = "yolov8n.pt"  # nano — smallest; users can override


class YOLODetector:
    """YOLO v8 component detector.

    Parameters
    ----------
    model_path:
        Path to a YOLOv8 weights file (.pt) or a model name understood by
        Ultralytics (e.g. ``"yolov8n.pt"``).  Defaults to ``yolov8n.pt``.
    confidence:
        Minimum detection confidence threshold (0–1).
    device:
        Inference device, e.g. ``"cpu"``, ``"cuda:0"``, ``"mps"``.
        ``None`` lets Ultralytics auto-select.
    """

    def __init__(
        self,
        model_path: str | Path = _DEFAULT_MODEL,
        confidence: float = 0.35,
        device: str | None = None,
    ) -> None:
        self._model_path = str(model_path)
        self._confidence = confidence
        self._device = device
        self._model: Any = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'ultralytics' package is required for YOLO-based detection.\n"
                "Install it with:  pip install ultralytics\n"
                f"Original error: {exc}"
            ) from exc

        logger.info("Loading YOLO model from: %s", self._model_path)
        kwargs: dict[str, Any] = {}
        if self._device is not None:
            kwargs["device"] = self._device
        self._model = YOLO(self._model_path, **kwargs)
        logger.info("YOLO model loaded.")

    def detect(self, image: np.ndarray) -> list[Component]:
        """Run inference on *image* and return detected components.

        Parameters
        ----------
        image:
            BGR or RGB numpy array (H × W × 3), as returned by OpenCV or PIL.

        Returns
        -------
        List of :class:`~retrace.core.pipeline.Component` instances, one per
        detected bounding box above the confidence threshold.
        """
        if self._model is None:
            logger.error("YOLO model is not loaded — returning empty detections.")
            return []

        try:
            results = self._model.predict(
                source=image,
                conf=self._confidence,
                verbose=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("YOLO inference failed: %s", exc)
            return []

        components: list[Component] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                # box.xyxy: [[x1, y1, x2, y2]]
                coords = box.xyxy[0].tolist()
                x1, y1, x2, y2 = (int(v) for v in coords)
                w, h = x2 - x1, y2 - y1

                cls_idx = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                label = _LABEL_MAP.get(cls_idx, f"class_{cls_idx}")

                components.append(
                    Component(
                        id=f"D{uuid.uuid4().hex[:8]}",
                        label=label,
                        confidence=round(conf, 4),
                        bbox=(x1, y1, w, h),
                    )
                )

        logger.debug("YOLO detected %d component(s)", len(components))
        return components
