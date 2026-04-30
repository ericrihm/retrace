"""OCR module for reading chip markings on PCB components.

Crops each component's bounding box from the board image, runs OCR (EasyOCR),
and returns an updated component list with the ``marking`` field populated.

Falls back gracefully when ``easyocr`` is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from retrace.core.pipeline import Component

logger = logging.getLogger(__name__)

# Minimum crop area (pixels²) — tiny crops produce junk OCR results
_MIN_CROP_AREA = 64

# Components worth running OCR on (others are too small or featureless)
_OCR_LABELS = {"ic", "crystal", "inductor", "diode", "transistor"}


def read_markings(
    img: np.ndarray,
    components: list[Component],
    languages: list[str] | None = None,
    gpu: bool = False,
) -> list[Component]:
    """Read chip markings for each component in *components*.

    Parameters
    ----------
    img:
        Full board image (BGR or RGB numpy array).
    components:
        Detected components whose ``bbox`` fields define crop regions.
    languages:
        EasyOCR language codes.  Defaults to ``["en"]``.
    gpu:
        Whether to use GPU for EasyOCR inference.

    Returns
    -------
    Updated component list with ``marking`` field populated where OCR
    produced a confident result.  Components without a marking are
    returned unchanged.

    Raises
    ------
    Nothing — all errors are caught and logged; the original component
    list is returned on failure.
    """
    if languages is None:
        languages = ["en"]

    reader = _get_reader(languages=languages, gpu=gpu)
    if reader is None:
        # easyocr not available — return unchanged
        return components

    updated: list[Component] = []
    for comp in components:
        if comp.label not in _OCR_LABELS:
            updated.append(comp)
            continue

        crop = _crop_component(img, comp.bbox)
        if crop is None or crop.size < _MIN_CROP_AREA:
            updated.append(comp)
            continue

        marking = _run_ocr(reader, crop)
        if marking:
            import dataclasses
            comp = dataclasses.replace(comp, marking=marking)
        updated.append(comp)

    return updated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_reader_cache: dict[str, Any] = {}


def _get_reader(languages: list[str], gpu: bool) -> Any | None:
    """Return a cached EasyOCR Reader, or None if unavailable."""
    cache_key = f"{'_'.join(sorted(languages))}_{gpu}"
    if cache_key in _reader_cache:
        return _reader_cache[cache_key]

    try:
        import easyocr  # type: ignore[import]
    except ImportError:
        logger.warning(
            "easyocr is not installed — chip marking OCR is disabled.\n"
            "Install it with:  pip install easyocr"
        )
        return None

    try:
        logger.info("Initialising EasyOCR reader (languages=%s, gpu=%s)", languages, gpu)
        reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
        _reader_cache[cache_key] = reader
        return reader
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialise EasyOCR: %s", exc)
        return None


def _crop_component(img: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
    """Crop the component region from *img*.

    Parameters
    ----------
    img:
        Full image array (H × W × C).
    bbox:
        ``(x, y, width, height)`` bounding box.

    Returns
    -------
    Cropped sub-image, or ``None`` if the crop is out of bounds.
    """
    x, y, w, h = bbox
    if w <= 0 or h <= 0:
        return None

    img_h, img_w = img.shape[:2]

    # Clamp to image bounds
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img_w, x + w)
    y2 = min(img_h, y + h)

    if x2 <= x1 or y2 <= y1:
        return None

    # Add a small padding to include text near the border
    pad = max(2, int(min(w, h) * 0.05))
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img_w, x2 + pad)
    y2 = min(img_h, y2 + pad)

    return img[y1:y2, x1:x2]


def _run_ocr(reader: Any, crop: np.ndarray) -> str:
    """Run EasyOCR on *crop* and return the best text result.

    Filters out results with confidence < 0.4 and joins remaining
    detections with spaces.

    Parameters
    ----------
    reader:
        Initialised ``easyocr.Reader`` instance.
    crop:
        Cropped component image.

    Returns
    -------
    Cleaned text string, or ``""`` if nothing was detected.
    """
    try:
        results = reader.readtext(crop, detail=1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("EasyOCR readtext failed: %s", exc)
        return ""

    # results: list of [bbox, text, confidence]
    tokens: list[str] = []
    for _bbox, text, confidence in results:
        if confidence >= 0.4 and text.strip():
            tokens.append(text.strip())

    if not tokens:
        return ""

    marking = " ".join(tokens)
    # Normalise whitespace
    marking = " ".join(marking.split())
    return marking
